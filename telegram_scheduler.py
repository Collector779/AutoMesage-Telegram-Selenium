import time
import random
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

from telegram_scan import _find_message_input, _find_topics, _go_back_from_topic
from config import MESSAGE_TO_SEND


def _split_chat_display(name: str):
    """Return (group_name, topic_name) for entries like 'Group / Topic'."""
    if not name:
        return "", None
    parts = name.split(" / ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, None


def _click_locator_with_retries(driver, locator, description, max_attempts=3):
    """Scroll into view and click an element, retrying on transient failures."""
    last_exception = None
    for _ in range(max_attempts):
        try:
            element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(locator)
            )
        except Exception as err:
            last_exception = err
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass
        try:
            element.click()
            return element
        except ElementClickInterceptedException:
            print(f"  -> DEBUG: Klikniecie {description} przechwycone, ponawiam...")
            time.sleep(0.3)
            continue
        except StaleElementReferenceException:
            print(f"  -> DEBUG: Element {description} jest nieaktualny, odswiezam...")
            continue
        except Exception as err:
            print(f"  -> DEBUG: Blad klikniecia {description}: {err}")
            last_exception = err
            break
    try:
        element = driver.find_element(*locator)
        driver.execute_script("arguments[0].click();", element)
        print(f"  -> DEBUG: Klikniecie {description} wykonane przez JS.")
        return element
    except Exception as js_err:
        print(f"  -> DEBUG: Nie udalo sie kliknac {description} (JS): {js_err}")
        if last_exception:
            raise last_exception
        raise


def _click_element_with_refresh(driver, element, description, refresh_callback=None, max_attempts=3):
    """Click an existing WebElement; optionally refresh the reference when stale."""
    last_exception = None
    for _ in range(max_attempts):
        if element is None:
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass
        try:
            element.click()
            return element
        except ElementClickInterceptedException:
            print(f"  -> DEBUG: Klikniecie {description} przechwycone, ponawiam...")
            time.sleep(0.3)
            continue
        except StaleElementReferenceException as stale_err:
            print(f"  -> DEBUG: Element {description} jest nieaktualny, odswiezam...")
            last_exception = stale_err
        except Exception as err:
            print(f"  -> DEBUG: Blad klikniecia {description}: {err}")
            last_exception = err
            break

        if refresh_callback:
            element = refresh_callback()
        else:
            element = None

    if refresh_callback:
        element = refresh_callback()

    if element is not None:
        try:
            driver.execute_script("arguments[0].click();", element)
            print(f"  -> DEBUG: Klikniecie {description} wykonane przez JS.")
            return element
        except Exception as js_err:
            print(f"  -> DEBUG: Nie udalo sie kliknac {description} (JS): {js_err}")
            last_exception = last_exception or js_err

    raise last_exception or Exception(f"Nie udalo sie kliknac {description}.")


def _open_chat_target(driver, chat_info):
    """Open the requested chat or forum topic and return an active input element."""
    chat_name = chat_info.get('name') or ''
    peer_id = chat_info.get('peer_id')
    thread_id = chat_info.get('thread_id')

    group_name, topic_name = _split_chat_display(chat_name)

    group_locators = []
    if peer_id is not None:
        peer_id_str = str(peer_id)
        group_locators.extend([
            (By.CSS_SELECTOR, f"#column-left a.chatlist-chat[data-peer-id='{peer_id_str}']:not([data-thread-id])"),
            (By.CSS_SELECTOR, f"a.chatlist-chat[data-peer-id='{peer_id_str}']:not([data-thread-id])"),
            (By.CSS_SELECTOR, f"#column-left a.chatlist-chat[data-peer-id='{peer_id_str}']"),
            (By.CSS_SELECTOR, f"a.chatlist-chat[data-peer-id='{peer_id_str}']"),
        ])

    if not group_locators:
        safe_fragment = group_name.replace("'", "\"")
        group_locators.append(
            (By.XPATH, f"//div[@id='column-left']//a[contains(@class,'chatlist-chat') and contains(., '{safe_fragment[:40]}')]")
        )

    group_element = None
    for locator in group_locators:
        try:
            group_element = _click_locator_with_retries(driver, locator, f"czatu '{group_name}'")
            if group_element:
                break
        except Exception:
            continue

    if not group_element:
        raise Exception(f"Nie znaleziono czatu grupy '{group_name}'.")

    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//div[@id='column-center']"))
        )
    except Exception:
        time.sleep(0.5)

    if thread_id:
        thread_id_str = str(thread_id)

        def locate_topic():
            topics = _find_topics(driver)
            for topic in topics:
                tid = topic.get_attribute('data-thread-id') or topic.get_attribute('data-topic-id')
                if tid == thread_id_str:
                    return topic
            if topic_name:
                topic_lower = topic_name.lower()
                for topic in topics:
                    text = (topic.text or '').strip().lower()
                    if topic_lower and topic_lower in text:
                        return topic
            return None

        topic_element = None
        for _ in range(4):
            topic_element = locate_topic()
            if topic_element:
                break
            time.sleep(0.5)

        if not topic_element:
            topics = _find_topics(driver)
            debug_list = [
                (t.get_attribute('data-thread-id'), (t.text or '').strip())
                for t in topics
            ]
            raise Exception(
                f"Nie znaleziono tematu '{topic_name or thread_id_str}' w grupie '{group_name}'. Dostepne: {debug_list}"
            )

        _click_element_with_refresh(
            driver,
            topic_element,
            f"tematu '{topic_name or thread_id_str}'",
            refresh_callback=locate_topic,
        )

        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[@id='column-center']//div[contains(@class,'messages-container')]"))
            )
        except Exception:
            time.sleep(0.5)

    input_el = _find_message_input(driver, timeout=4)
    if not input_el:
        raise Exception("Brak aktywnego pola wiadomosci po otwarciu czatu.")

    return input_el, group_name, topic_name


def run_scheduler(driver, writable_chats):
    schedule = {}
    for chat in writable_chats:
        initial_delay = random.randint(60, 300)
        schedule[chat['name']] = {
            'info': chat,
            'next_send_time': time.time() + initial_delay,
        }

    print("\n--- Rozpoczynam nieskonczony cykl wysylania z indywidualnym harmonogramem ---")
    print("Poczatkowy harmonogram wysylek:")
    for chat_name, data in schedule.items():
        wait_time = data['next_send_time'] - time.time()
        if wait_time < 0:
            wait_time = 0
        minutes = int(wait_time // 60)
        seconds = int(wait_time % 60)
        print(f"- {chat_name}: pierwsza wiadomosc za okolo {minutes} min. i {seconds} sek.")

    print("\nAby zatrzymac, nacisnij Ctrl+C w tym oknie.")

    while True:
        current_time = time.time()
        for key_name, data in schedule.items():
            chat_info = data.get('info', {})
            chat_name = chat_info.get('name', key_name)

            if current_time >= data['next_send_time']:
                print(f"\nNadszedl czas na wyslanie wiadomosci do: {chat_name}")
                try:
                    try:
                        old_header = driver.find_element(By.XPATH, "//div[@id='column-center']//span[contains(@class, 'peer-title')]")
                    except Exception:
                        old_header = None

                    message_input, group_name, topic_name = _open_chat_target(driver, chat_info)

                    if old_header:
                        try:
                            WebDriverWait(driver, 10).until(EC.staleness_of(old_header))
                        except Exception:
                            pass

                    header_elements = driver.find_elements(By.XPATH, "//div[@id='column-center']//span[contains(@class, 'peer-title')]")
                    header_text = " | ".join([el.text for el in header_elements if el.text])
                    if topic_name and topic_name not in header_text and group_name not in header_text:
                        print(f"  -> DEBUG: Naglowek '{header_text}' nie zawiera oczekiwanego tematu '{topic_name}'.")

                    try:
                        driver.execute_script("arguments[0].focus();", message_input)
                    except Exception:
                        try:
                            message_input.click()
                        except Exception:
                            pass

                    message_input.send_keys(MESSAGE_TO_SEND)
                    time.sleep(1)
                    send_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'btn-send')]"))
                    )
                    send_button.click()
                    print("  -> Wiadomosc wyslana pomyslnie.")

                    if chat_info.get('thread_id'):
                        for _ in range(4):
                            topics_present = _find_topics(driver)
                            if not topics_present:
                                break
                            if not _go_back_from_topic(driver):
                                break
                            time.sleep(0.2)

                    delay = random.randint(4200, 9840)
                    data['next_send_time'] = current_time + delay

                    wait_minutes, _ = divmod(delay, 60)
                    wait_hours, wait_minutes_rem = divmod(wait_minutes, 60)
                    print(f"  -> Nastepna wysylka do '{chat_name}' za {wait_hours} godz. i {wait_minutes_rem} min.")

                except Exception as e:
                    print(f"  -> Blad podczas wysylania do '{chat_name}': {e}")
                    data['next_send_time'] = current_time + 1800
                    print("  -> Sprobuje ponownie za 30 minut.")
                    continue

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n({timestamp}) Sprawdzono harmonogram. Nastepne sprawdzenie za 60 sek.")
        time.sleep(60)