import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService

from config import TELEGRAM_WEB_URL, find_chrome_binary, find_chromedriver_for, profile_dir

PROXY_TYPES = ("http", "https", "socks5", "socks4")


def proxy_url(proxy):
    """Return 'scheme://host:port' for an enabled, filled-in proxy config, else None."""
    if not proxy or not proxy.get("enabled"):
        return None
    host = str(proxy.get("host", "")).strip()
    port = str(proxy.get("port", "")).strip()
    if not host or not port:
        return None
    scheme = proxy.get("type", "http").lower()
    if scheme not in PROXY_TYPES:
        scheme = "http"
    return f"{scheme}://{host}:{port}"


def proxy_needs_auth(proxy):
    return bool(proxy_url(proxy) and str(proxy.get("username", "")).strip())


def start_browser(headless=True, proxy_server=None):
    """Start Chrome with a persistent profile. Selenium Manager fetches chromedriver if needed.

    proxy_server: 'scheme://host:port' passed to Chrome (no credentials; see proxy_relay).
    """
    options = webdriver.ChromeOptions()
    binary = find_chrome_binary()
    if binary:
        options.binary_location = binary
    if headless:
        options.add_argument("--headless=new")
    # Desktop-sized window, otherwise Telegram Web switches to its mobile layout.
    options.add_argument("--window-size=1400,1000")
    options.add_argument(f"--user-data-dir={profile_dir()}")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-notifications")
    options.add_argument("--mute-audio")
    if not sys.platform.startswith("win"):
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

    if proxy_server:
        options.add_argument(f"--proxy-server={proxy_server}")
        options.add_argument("--proxy-bypass-list=<-loopback>")
        # never leak the real IP through WebRTC when a proxy is set
        options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    driver_path = find_chromedriver_for(binary)
    service = ChromeService(executable_path=driver_path) if driver_path else ChromeService()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Headless Chrome announces itself as "HeadlessChrome"; present a normal user agent.
        ua = driver.execute_script("return navigator.userAgent")
        if "HeadlessChrome" in ua:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {"userAgent": ua.replace("HeadlessChrome", "Chrome")},
            )
    except Exception:
        driver.quit()
        raise

    driver.get(TELEGRAM_WEB_URL)
    return driver


def check_public_ip(driver, timeout=20):
    """Open a temporary tab, read the public IP the browser is seen with, return to Telegram."""
    main = driver.current_window_handle
    driver.switch_to.new_window("tab")
    try:
        driver.set_page_load_timeout(timeout)
        driver.get("https://api.ipify.org/")
        return driver.find_element("tag name", "body").text.strip()
    finally:
        driver.set_page_load_timeout(300)
        driver.close()
        driver.switch_to.window(main)
