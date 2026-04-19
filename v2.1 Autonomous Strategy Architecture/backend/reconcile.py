import asyncio
from main.logger import get_logger
from data_collector.router import get_mt5

log = get_logger("reconcile")

async def startup_reconcile():
    """
    Run once at application startup.
    Fetches all open positions from MT5.
    If a position has an 'AUTO:' comment, we parse the scanner_id.
    Since no scanners are running yet, ALL matching tags are considered ORPHANS.
    We also prepopulate the AutoExecutor's deduplication cache with signal IDs
    from these open positions so if the scanner restarts, it doesn't double-enter.
    """
    mt5 = get_mt5()
    if not mt5.connected:
        log.warning("startup_reconcile: MT5 not connected; skipping.")
        return

    try:
        positions = await asyncio.to_thread(mt5._session.positions_get)
        if positions is None:
            log.warning("startup_reconcile: Could not retrieve positions.")
            return

        from order.auto_executor import AutoExecutor
        auto_exec = AutoExecutor.get()

        orphans_detected = 0
        dedup_count = 0

        for pos in positions:
            comment = getattr(pos, "comment", "")
            if comment.startswith("AUTO:"):
                # Format: AUTO:{scanner_id_hex}:{signal_id_hex}
                parts = comment.split(":")
                if len(parts) >= 3:
                    scanner_hex = parts[1]
                    sig_hex = parts[2]
                    
                    # 1. Preload dedup cache
                    auto_exec._processed_signal_ids.add(sig_hex)
                    dedup_count += 1
                    
                    # 2. Add to orphans
                    auto_exec._orphan_positions.append({
                        "ticket": pos.ticket,
                        "symbol": pos.symbol,
                        "type": "BUY" if pos.type == 0 else "SELL",
                        "volume": pos.volume,
                        "price_open": pos.price_open,
                        "scanner_hex": scanner_hex,
                        "signal_id": sig_hex
                    })
                    orphans_detected += 1

        if orphans_detected > 0:
            log.warning(
                f"Startup Reconcile Found {orphans_detected} Orphan Positions! "
                f"Populated dedup cache with {dedup_count} hashes."
            )
        else:
            log.info("Startup reconcile clean — no orphans found.")

    except Exception as e:
        log.error(f"startup_reconcile failed: {e}", exc_info=True)
