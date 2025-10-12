import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from config import CHROME_BINARY

def start_browser():
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_BINARY
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def wait_for_login(driver, timeout=300):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    print("Oczekiwanie na zalogowanie...")
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//input[contains(@class, 'input-search-input')]"))
    )
    print("Zalogowano pomyslnie!")