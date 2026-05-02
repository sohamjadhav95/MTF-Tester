import asyncio
from signals.bus import SignalBus

async def run_test():
    bus = SignalBus()

    # 1. Normal transient subscriber
    def transient_cb(msg):
        raise RuntimeError("already disconnected")

    bus._global_subscribers.append(transient_cb)

    # 2. Service subscriber
    def service_cb(msg):
        raise Exception("Service crash!")

    bus.subscribe_service(service_cb)

    await bus.publish_trade_update({"symbol": "EURUSD"})

    assert len(bus._global_subscribers) == 0, "Transient SHOULD be removed"
    assert len(bus._service_subscribers) == 1, "Service SHOULD NOT be removed"

if __name__ == "__main__":
    asyncio.run(run_test())
    print("test_bus_removal passed!")
