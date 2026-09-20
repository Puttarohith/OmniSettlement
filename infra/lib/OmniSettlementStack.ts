import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as path from 'path';

export class OmniSettlementStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ==========================================
    // 1. KMS Customer Managed Key (CMK)
    // ==========================================
    const settlementKmsKey = new kms.Key(this, 'OmniSettlementKmsKey', {
      description: 'KMS CMK for OmniSettlement ledger, audit vault, and queue encryption',
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ==========================================
    // 2. S3 Audit & Evidence Vault (WORM Compliance)
    // ==========================================
    const auditBucket = new s3.Bucket(this, 'OmniSettlementAuditVault', {
      bucketName: `omnisettlement-audit-vault-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: settlementKmsKey,
      versioned: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.compliance(cdk.Duration.days(90)),
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ==========================================
    // 3. DynamoDB Tables
    // ==========================================
    // Table A: Distributed Idempotency and State Store
    const idempotencyTable = new dynamodb.Table(this, 'IdempotencyAndStateTable', {
      tableName: 'IdempotencyAndState',
      partitionKey: { name: 'idempotency_key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expires_at',
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: settlementKmsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Table B: Multi-Party Marketplace Ledger (Double-Entry Bookkeeping)
    const ledgerTable = new dynamodb.Table(this, 'MarketplaceLedgerTable', {
      tableName: 'MarketplaceLedger',
      partitionKey: { name: 'account_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'entry_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: settlementKmsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI: Query transactions by Order ID across all parties
    ledgerTable.addGlobalSecondaryIndex({
      indexName: 'OrderIdIndex',
      partitionKey: { name: 'order_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.NUMBER },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ==========================================
    // 4. SQS FIFO Queues (Ingestion & DLQ)
    // ==========================================
    const settlementDLQ = new sqs.Queue(this, 'SettlementDLQ', {
      queueName: 'SettlementDLQ.fifo',
      fifo: true,
      contentBasedDeduplication: true,
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: settlementKmsKey,
    });

    const settlementQueue = new sqs.Queue(this, 'SettlementQueue', {
      queueName: 'SettlementQueue.fifo',
      fifo: true,
      contentBasedDeduplication: true,
      visibilityTimeout: cdk.Duration.seconds(300),
      deadLetterQueue: {
        queue: settlementDLQ,
        maxReceiveCount: 3,
      },
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: settlementKmsKey,
    });

    // ==========================================
    // 5. Lambda Functions (Microservices)
    // ==========================================
    const lambdaEnv = {
      IDEMPOTENCY_TABLE: idempotencyTable.tableName,
      MARKETPLACE_LEDGER_TABLE: ledgerTable.tableName,
      SQS_QUEUE_URL: settlementQueue.queueUrl,
      AUDIT_BUCKET: auditBucket.bucketName,
      BEDROCK_MODEL_ID: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
      AWS_NODEJS_CONNECTION_REUSE_ENABLED: '1',
    };

    const pythonRuntime = lambda.Runtime.PYTHON_3_10;
    const lambdaCode = lambda.Code.fromAsset(path.join(__dirname, '../../'), {
      exclude: [
        'infra',
        'infra/**',
        'cdk.out',
        'cdk.out/**',
        'node_modules',
        'node_modules/**',
        '.git',
        '.git/**',
        '.pytest_cache',
        '.pytest_cache/**',
        '__pycache__',
        '**/__pycache__',
        'tests',
        'tests/**'
      ],
    });

    // Lambda 1: Ingestion & Idempotency Check
    const ingestionLambda = new lambda.Function(this, 'IngestionLambda', {
      functionName: 'OmniSettlement-IngestionHandler',
      runtime: pythonRuntime,
      handler: 'services.ingestion.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(10),
      environment: lambdaEnv,
    });

    // Least-Privilege IAM for Ingestion Lambda
    idempotencyTable.grantReadWriteData(ingestionLambda);
    settlementQueue.grantSendMessages(ingestionLambda);
    settlementKmsKey.grantEncryptDecrypt(ingestionLambda);

    // Lambda 2: Telemetry Aggregator
    const telemetryLambda = new lambda.Function(this, 'TelemetryAggregatorLambda', {
      functionName: 'OmniSettlement-TelemetryAggregator',
      runtime: pythonRuntime,
      handler: 'services.telemetry_aggregator.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(30),
      environment: lambdaEnv,
    });
    auditBucket.grantRead(telemetryLambda);

    // Lambda 3: Bedrock Extraction Engine
    const bedrockLambda = new lambda.Function(this, 'BedrockExtractorLambda', {
      functionName: 'OmniSettlement-BedrockExtractor',
      runtime: pythonRuntime,
      handler: 'services.bedrock_extractor.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(60),
      environment: lambdaEnv,
    });
    // Bedrock Invoke Policy
    bedrockLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: [
        `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0`,
        `arn:aws:bedrock:*::foundation-model/*`
      ],
    }));

    // Lambda 4: Invariant & Zero-Sum Calculation Engine
    const invariantLambda = new lambda.Function(this, 'InvariantEngineLambda', {
      functionName: 'OmniSettlement-InvariantEngine',
      runtime: pythonRuntime,
      handler: 'services.invariant_engine.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(15),
      environment: lambdaEnv,
    });

    // Lambda 5: Multi-Ledger TransactWriter
    const ledgerWriterLambda = new lambda.Function(this, 'LedgerWriterLambda', {
      functionName: 'OmniSettlement-LedgerWriter',
      runtime: pythonRuntime,
      handler: 'services.ledger_writer.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(30),
      environment: lambdaEnv,
    });
    ledgerTable.grantReadWriteData(ledgerWriterLambda);
    idempotencyTable.grantReadWriteData(ledgerWriterLambda);
    settlementKmsKey.grantEncryptDecrypt(ledgerWriterLambda);

    // Lambda 6: Stripe Dispatcher & Saga Compensator
    const stripeLambda = new lambda.Function(this, 'StripeDispatcherLambda', {
      functionName: 'OmniSettlement-StripeDispatcher',
      runtime: pythonRuntime,
      handler: 'services.stripe_dispatcher.handler',
      code: lambdaCode,
      timeout: cdk.Duration.seconds(30),
      environment: lambdaEnv,
    });

    // ==========================================
    // 6. Step Functions: Compensating Saga Workflow
    // ==========================================
    const rollbackTask = new tasks.LambdaInvoke(this, 'ExecuteCompensatingRollback', {
      lambdaFunction: stripeLambda,
      payload: sfn.TaskInput.fromObject({
        is_rollback: true,
        order_id: sfn.JsonPath.stringAt('$.order_id'),
        reason: 'Saga step failed. Executing compensating rollback.',
      }),
      resultPath: '$.rollback_result',
    });

    const aggregateTask = new tasks.LambdaInvoke(this, 'AggregateTelemetryStep', {
      lambdaFunction: telemetryLambda,
      outputPath: '$.Payload',
    });

    const extractTask = new tasks.LambdaInvoke(this, 'ExtractTimelineBedrockStep', {
      lambdaFunction: bedrockLambda,
      outputPath: '$.Payload',
    });

    const computePlanTask = new tasks.LambdaInvoke(this, 'ComputeZeroSumPlanStep', {
      lambdaFunction: invariantLambda,
      outputPath: '$.Payload',
    });

    const writeLedgerTask = new tasks.LambdaInvoke(this, 'CommitLedgerTransactStep', {
      lambdaFunction: ledgerWriterLambda,
      outputPath: '$.Payload',
    });

    const dispatchStripeTask = new tasks.LambdaInvoke(this, 'DispatchStripeGatewayStep', {
      lambdaFunction: stripeLambda,
      outputPath: '$.Payload',
    });

    // Chain with error catching and compensation
    aggregateTask.addCatch(rollbackTask, { resultPath: '$.error' });
    extractTask.addCatch(rollbackTask, { resultPath: '$.error' });
    computePlanTask.addCatch(rollbackTask, { resultPath: '$.error' });
    writeLedgerTask.addCatch(rollbackTask, { resultPath: '$.error' });
    dispatchStripeTask.addCatch(rollbackTask, { resultPath: '$.error' });

    // Choice branch: Check if human review is required
    const checkHumanReview = new sfn.Choice(this, 'RequiresHumanReviewChoice');
    const humanReviewState = new sfn.Pass(this, 'EscrowHeldForHumanReview', {
      result: sfn.Result.fromObject({
        status: 'PENDING_HUMAN_ARBITRATION',
        message: 'Dispute flagged for manual review due to low confidence or policy threshold.',
      }),
      resultPath: '$.arbitration_status',
    });

    const sagaDefinition = aggregateTask
      .next(extractTask)
      .next(computePlanTask)
      .next(
        checkHumanReview
          .when(
            sfn.Condition.booleanEquals('$.settlement_plan.requires_human_review', true),
            humanReviewState
          )
          .otherwise(
            writeLedgerTask
              .next(dispatchStripeTask)
          )
      );

    const sagaStateMachine = new sfn.StateMachine(this, 'OmniSettlementSagaMachine', {
      stateMachineName: 'OmniSettlement-DisputeSaga',
      definitionBody: sfn.DefinitionBody.fromChainable(sagaDefinition),
      timeout: cdk.Duration.minutes(10),
      tracingEnabled: true,
      logs: {
        destination: new cdk.aws_logs.LogGroup(this, 'SagaLogGroup', {
          retention: cdk.aws_logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: sfn.LogLevel.ALL,
      },
    });

    // ==========================================
    // 7. API Gateway REST API with HMAC Verification
    // ==========================================
    const api = new apigateway.RestApi(this, 'OmniSettlementApi', {
      restApiName: 'OmniSettlement Webhook & Dispute Ingestion Service',
      description: 'Ingests dispute and cancellation webhooks with HMAC validation and idempotency guarantees.',
      deployOptions: {
        stageName: 'prod',
        tracingEnabled: true,
        metricsEnabled: true,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'X-Signature-SHA256', 'Idempotency-Key', 'Authorization'],
      },
    });

    const webhooksResource = api.root.addResource('webhooks');
    const disputeResource = webhooksResource.addResource('dispute');
    
    disputeResource.addMethod('POST', new apigateway.LambdaIntegration(ingestionLambda, {
      proxy: true,
    }));

    // Stack Outputs
    new cdk.CfnOutput(this, 'ApiEndpointUrl', {
      value: api.url,
      description: 'API Gateway REST API Endpoint for Webhook Ingestion',
    });

    new cdk.CfnOutput(this, 'SagaStateMachineArn', {
      value: sagaStateMachine.stateMachineArn,
      description: 'Step Functions Saga State Machine ARN',
    });

    new cdk.CfnOutput(this, 'AuditVaultBucketName', {
      value: auditBucket.bucketName,
      description: 'S3 WORM Audit Vault Bucket Name',
    });
  }
}
