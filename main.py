from pathlib import Path
from datetime import datetime, timezone
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = "https://thanhthovn.github.io/1ptvsc4n/"
OUTPUT_DIR = Path("output")
MAX_SCAN_SECONDS = 4 * 60 * 60
POLL_SECONDS = 5


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(30_000)

        page.on("pageerror", lambda exc: errors.append(f"Page error: {exc}"))
        page.on("console", lambda msg: print(f"[browser:{msg.type}] {msg.text}") if msg.type == "error" else None)

        try:
            print(f"Opening {URL}")
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
            page.locator("#autoAllScanBtn").wait_for(state="visible", timeout=60_000)

            # Wait for the channel and link templates to finish loading.
            page.wait_for_function(
                """() => {
                    const channels = document.querySelector('#channelSelect');
                    const templates = document.querySelector('#templateSelect');
                    return channels && templates &&
                           channels.options.length > 0 &&
                           templates.options.length > 0;
                }""",
                timeout=90_000,
            )

            # This button performs the site's full automatic channel + link scan.
            print("Starting full automatic IPTV channel/link scan...")
            page.locator("#autoAllScanBtn").click()

            deadline = time.monotonic() + MAX_SCAN_SECONDS
            last_status = ""
            while time.monotonic() < deadline:
                page.wait_for_timeout(POLL_SECONDS * 1000)

                status_locator = page.locator("#autoAllStatus")
                status = status_locator.inner_text().strip() if status_locator.count() else ""
                if status and status != last_status:
                    print(f"[scan] {status}")
                    last_status = status

                normalized = status.casefold()
                if "đã dò xong" in normalized or "dò tự động hoàn tất" in normalized:
                    break

                # Stop early on a visible error if the site did not start scanning.
                body_text = page.locator("body").inner_text().casefold()
                if not status and ("chưa có danh sách kênh" in body_text or "chưa nạp được" in body_text):
                    raise RuntimeError("Trang chưa tải được danh sách kênh/link cần thiết.")
            else:
                raise TimeoutError(f"Automatic scan did not finish within {MAX_SCAN_SECONDS // 60} minutes.")

            found_text = page.locator("#foundLinks").inner_text().strip()
            try:
                found_count = int(found_text)
            except ValueError:
                found_count = 0

            final_text = page.locator("body").inner_text().strip()
            (OUTPUT_DIR / "ket_qua.txt").write_text(final_text, encoding="utf-8")
            (OUTPUT_DIR / "scan-summary.txt").write_text(
                f"Started: {started}\n"
                f"Finished: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}\n"
                f"Found working links: {found_count}\n"
                f"Final scan status: {last_status}\n",
                encoding="utf-8",
            )

            print(f"Scan complete. Found links: {found_count}")
            if found_count <= 0:
                print("No working links found; skipping M3U export.")
                return

            export_button = page.locator("#exportM3uBtn")
            export_button.wait_for(state="visible", timeout=30_000)
            page.wait_for_function(
                "() => { const b = document.querySelector('#exportM3uBtn'); return b && !b.disabled; }",
                timeout=60_000,
            )

            print("Exporting M3U...")
            with page.expect_download(timeout=30_000) as download_info:
                export_button.click()

            download = download_info.value
            suggested = Path(download.suggested_filename).name
            if not suggested.lower().endswith(".m3u"):
                suggested = "m3uiptv_result.m3u"
            destination = OUTPUT_DIR / suggested
            download.save_as(str(destination))
            print(f"M3U saved to {destination}")

            (OUTPUT_DIR / "browser-errors.txt").write_text(
                "\n".join(errors) if errors else "No browser page errors recorded.\n",
                encoding="utf-8",
            )

        except Exception:
            try:
                page.screenshot(path=str(OUTPUT_DIR / "error.png"), full_page=True)
                (OUTPUT_DIR / "error-page.txt").write_text(
                    page.locator("body").inner_text(), encoding="utf-8"
                )
            except Exception:
                pass
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
