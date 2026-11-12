import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService

from config import TELEGRAM_WEB_URL, find_chrome_binary, find_chromedriver_for, profile_dir


def start_browser(headless=True):
    """Start Chrome with a persistent profile. Selenium Manager fetches chromedriver if needed."""
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

    driver_path = find_chromedriver_for(binary)
    service = ChromeService(executable_path=driver_path) if driver_path else ChromeService()
    driver = webdriver.Chrome(service=service, options=options)

    # Headless Chrome announces itself as "HeadlessChrome"; present a normal user agent.
    try:
        ua = driver.execute_script("return navigator.userAgent")
        if "HeadlessChrome" in ua:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {"userAgent": ua.replace("HeadlessChrome", "Chrome")},
            )
    except Exception:
        pass

    driver.get(TELEGRAM_WEB_URL)
    return driver
