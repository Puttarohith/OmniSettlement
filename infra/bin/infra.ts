#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { OmniSettlementStack } from '../lib/OmniSettlementStack';

const app = new cdk.App();
new OmniSettlementStack(app, 'OmniSettlementStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT || '123456789012',
    region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
  },
  description: 'OmniSettlement: Multi-Party Marketplace Settlement & Dispute Reconciliation Platform'
});
