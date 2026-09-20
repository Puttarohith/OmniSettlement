"""
Traffic Simulator Script
Generates continuous, realistic multi-party dispute workloads against the OmniSettlement API endpoint.
"""
import time
import random
import httpx
import uuid


SERVER_URL = "http://127.0.0.1:8000"
SCENARIOS = [
    "CUSTOMER_LATE_CANCEL",
    "MERCHANT_KITCHEN_FAILURE",
    "PROMPT_INJECTION_ATTACK",
    "LOW_CONFIDENCE_ARBITRATION",
    "DUPLICATE_REPLAY_ATTACK"
]


def run_traffic_simulation(num_events: int = 25, delay_sec: float = 0.5):
    print("=" * 65)
    print(f"STARTING OMNISETTLEMENT TRAFFIC SIMULATION ({num_events} EVENTS)")
    print(f"Target Endpoint: {SERVER_URL}/api/chaos/inject")
    print("=" * 65)

    client = httpx.Client(timeout=10.0)
    success_count = 0
    total_time_ms = []

    for i in range(1, num_events + 1):
        scenario = random.choice(SCENARIOS)
        start_t = time.perf_counter()
        
        try:
            res = client.post(f"{SERVER_URL}/api/chaos/inject", json={"scenario": scenario})
            elapsed = (time.perf_counter() - start_t) * 1000.0
            total_time_ms.append(elapsed)

            if res.status_code == 200:
                data = res.json()
                status = data.get("status", "UNKNOWN")
                order_id = data.get("order_id", f"EVENT-{i}")
                print(f"[{i:02d}/{num_events}] Scenario: {scenario:<28} | Order: {order_id} | Status: {status:<15} | Latency: {elapsed:.2f} ms")
                success_count += 1
            else:
                print(f"[{i:02d}/{num_events}] FAILED: Status {res.status_code} - {res.text}")

        except Exception as e:
            print(f"[{i:02d}/{num_events}] Error connecting: {str(e)}")

        time.sleep(delay_sec)

    if total_time_ms:
        avg_lat = sum(total_time_ms) / len(total_time_ms)
        print("=" * 65)
        print(f"SIMULATION COMPLETE: {success_count}/{num_events} events processed successfully.")
        print(f"Average Round-Trip Latency: {avg_lat:.2f} ms")
        print("=" * 65)


if __name__ == "__main__":
    run_traffic_simulation()
