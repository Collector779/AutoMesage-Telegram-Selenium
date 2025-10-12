import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

# === Helpers for forum groups (tematy/podczaty) ===
def _find_message_input(driver, timeout=2):
    """Locate an active message input inside the center column."""
    xpaths = [
        "//div[@id='column-center']//div[contains(@class, 'input-message-input') and @contenteditable='true']",
        "//div[@id='column-center']//div[@role='textbox' and @contenteditable='true']",
        "//div[@id='column-center']//div[@contenteditable='true' and (@data-placeholder or @aria-label)]",
    ]
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            if el and el.is_displayed():
                return el
        except Exception:
            pass
    return None


def _find_topics(driver):
    """Return visible forum topic elements (sub-chats) when present."""
    topic_xpaths = [
        "//div[@id='column-center']//a[contains(@class,'chatlist-chat') and @data-thread-id]",
        "//div[@id='column-center']//a[@data-thread-id]",
        "//div[@id='column-center']//div[contains(@class,'forum') or contains(@class,'topic') or contains(@class,'thread')]//a[@data-thread-id]",
        "//div[@id='column-left']//a[contains(@class,'chatlist-chat') and @data-thread-id]",
        "//div[@id='column-left']//div[contains(@class,'forum') or contains(@class,'topic') or contains(@class,'thread')]//a[@data-thread-id]",
    ]
    for xp in topic_xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
            visible = [e for e in elems if e.is_displayed()]
            if visible:
                return visible
        except Exception:
            continue
    return []


def _go_back_from_topic(driver):
    """Leave topic view using header buttons or ESC fallback."""
    back_xpaths = [
        "//div[@id='column-center']//button[contains(@class,'back')]",
        "//div[@id='column-center']//button[contains(@class,'header-back') or contains(@class,'header__back')]",
        "//div[@id='column-center']//button[contains(@class,'btn-icon')][.//span[contains(@class,'tgico')]]",
        "//div[@id='column-center']//button[contains(@class,'close') or contains(@class,'header-close')]",
        "//div[@id='column-center']//button[contains(@aria-label,'Back')]",
        "//div[@id='column-center']//button[contains(@aria-label,'Close')]",
    ]
    for xp in back_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.3)
                return True
        except Exception:
            pass
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ESCAPE)
        time.sleep(0.2)
        return True
    except Exception:
        return False


def scan_all_chats(driver, max_no_grow=12):
    """Scroll chat list until no new items load; return Selenium chat elements."""
    chat_list_element = driver.find_element(By.ID, "column-left")
    last_count = 0
    no_grow_count = 0
    scroll_step = 200

    print("Przewijam liste czatow do konca...")

    while no_grow_count < max_no_grow:
        chats = chat_list_element.find_elements(By.XPATH, ".//a[contains(@class, 'chatlist-chat')]")
        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollTop + arguments[1]",
            chat_list_element,
            scroll_step,
        )
        time.sleep(1)
        new_chats = chat_list_element.find_elements(By.XPATH, ".//a[contains(@class, 'chatlist-chat')]")
        if len(new_chats) > last_count:
            last_count = len(new_chats)
            no_grow_count = 0
        else:
            no_grow_count += 1
    print(f"Zaladowano {last_count} czatow.")
    return chat_list_element.find_elements(By.XPATH, ".//a[contains(@class, 'chatlist-chat')]")


def filter_group_chats(chats, driver):
    writable_chats = []

    for i, chat in enumerate(chats):
        # upewnij się, że referencja do czatu nie jest przeterminowana
        try:
            chat.get_attribute("data-peer-id")
        except StaleElementReferenceException:
            print("  -> DEBUG: Referencja czatu jest nieaktualna, odswiezam...")
            try:
                refreshed_chats = driver.find_element(By.ID, "column-left").find_elements(
                    By.XPATH, ".//a[contains(@class, 'chatlist-chat')]"
                )
                if i < len(refreshed_chats):
                    chat = refreshed_chats[i]
                    chats[i] = chat
                else:
                    scan_all_chats(driver, max_no_grow=4)
                    refreshed_chats = driver.find_element(By.ID, "column-left").find_elements(
                        By.XPATH, ".//a[contains(@class, 'chatlist-chat')]"
                    )
                    if i < len(refreshed_chats):
                        chat = refreshed_chats[i]
                        chats[i] = chat
                    else:
                        print(f"  -> DEBUG: Brak czatu o indeksie {i+1} po odswiezeniu. Pomijam.")
                        continue
            except Exception as refresh_err:
                print(f"  -> DEBUG: Nie udalo sie odswiezyc czatu {i+1}: {refresh_err}. Pomijam.")
                continue
        try:
            chat_name_element = chat.find_element(
                By.XPATH,
                ".//div[contains(@class, 'row-title') and contains(@class, 'user-title')]//span[contains(@class, 'peer-title')] ",
            )
            chat_name = chat_name_element.text
            if not chat_name:
                continue

            print(f"Sprawdzam czat ({i + 1}/{len(chats)}): {chat_name}")
            is_group = False
            peer_id_str = chat.get_attribute("data-peer-id")
            print(f"  -> Weryfikacja grupy dla czatu: {chat_name} (ID: {peer_id_str})")

            try:
                peer_id = int(peer_id_str)
                if peer_id < 0:
                    is_group = True
                    print("    -> ID jest ujemne (prawdopodobnie grupa/kanal).")
                else:
                    print("    -> ID jest dodatnie. Szukam dodatkowych wskaznikow grupy.")
                    try:
                        chat.find_element(
                            By.XPATH,
                            ".//span[contains(@class, 'tgico dialog-muted-icon')] | .//i[contains(@class, 'icon-channel')] | .//i[contains(@class, 'icon-group')] ",
                        )
                        is_group = True
                        print("      -> Znaleziono ikone kanalu/grupy.")
                    except Exception:
                        try:
                            chat.find_element(
                                By.XPATH,
                                ".//span[contains(@class, 'dialog-subtitle-span') and (contains(text(), 'member') or contains(text(), 'subscriber'))]",
                            )
                            is_group = True
                            print("      -> Znaleziono tekst 'member'/'subscriber'.")
                        except Exception:
                            pass
            except (ValueError, TypeError):
                print(f"    -> Nie mozna sparsowac ID czatu ({peer_id_str}). Traktuje jako nie-grupe.")

            if not is_group:
                print("  -> To prawdopodobnie czat prywatny. Pomijam.")
                continue

            # Ensure chat is visible/clickable before clicking to avoid intercepts
            clicked = False
            for attempt in range(3):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chat)
                except Exception:
                    pass
                try:
                    chat.click()
                    clicked = True
                    break
                except ElementClickInterceptedException:
                    print("  -> DEBUG: Klikniecie zostalo przechwycone, probuje ponownie...")
                    time.sleep(0.3)
                    continue
                except StaleElementReferenceException:
                    print("  -> DEBUG: Element czatu jest nieaktualny, probuje ponownie wyszukac.")
                    try:
                        refreshed = driver.find_element(By.ID, "column-left").find_elements(
                            By.XPATH, ".//a[contains(@class, 'chatlist-chat')]"
                        )
                        if i < len(refreshed):
                            chat = refreshed[i]
                            chats[i] = chat
                        else:
                            scan_all_chats(driver, max_no_grow=4)
                            refreshed = driver.find_element(By.ID, "column-left").find_elements(
                                By.XPATH, ".//a[contains(@class, 'chatlist-chat')]"
                            )
                            if i < len(refreshed):
                                chat = refreshed[i]
                                chats[i] = chat
                            else:
                                break
                    except Exception:
                        break
                except Exception as click_err:
                    print(f"  -> DEBUG: Blad podczas klikania czatu: {click_err}")
                    break
            if not clicked:
                try:
                    driver.execute_script("arguments[0].click();", chat)
                    clicked = True
                    print("  -> DEBUG: Klikniecie wykonane przez JS.")
                except Exception as js_err:
                    print(f"  -> Blad: nie udalo sie kliknac czatu (JS): {js_err}. Pomijam.")
                    continue
            try:
                WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@id='column-center']"))
                )
            except Exception:
                time.sleep(1)

            peer_id_str = chat.get_attribute("data-peer-id")
            try:
                peer_id = int(peer_id_str)
                if peer_id >= 0:
                    print(f"  -> To czat prywatny (ID: {peer_id}). Pomijam.")
                    continue
            except (ValueError, TypeError):
                print(f"  -> Nie mozna zweryfikowac typu czatu (ID: {peer_id_str}). Pomijam.")
                continue

            # Try forum topics first
            try:
                current_url = driver.current_url
            except Exception:
                current_url = "(no url)"
            topics = _find_topics(driver)
            if topics:
                print(f"  -> Wykryto liste podczatow/tematow: {len(topics)} (URL: {current_url}).")
                topic_infos = []
                for idx, topic_el in enumerate(topics):
                    try:
                        thread_id = topic_el.get_attribute("data-thread-id")
                        topic_peer_id = topic_el.get_attribute("data-peer-id")
                        try:
                            topic_name_el = topic_el.find_element(By.XPATH, ".//span[contains(@class,'peer-title-inner')]")
                            topic_name = topic_name_el.text
                        except Exception:
                            topic_name = topic_el.text if topic_el.text else None
                        topic_name = (topic_name or "").strip()
                        topic_infos.append(
                            {
                                "thread_id": thread_id,
                                "peer_id": topic_peer_id,
                                "name": topic_name,
                            }
                        )
                        if idx < 10:
                            print(f"    -> DEBUG topic[{idx}]: id={thread_id} name='{topic_name[:80]}'")
                    except Exception as info_err:
                        print(f"    -> DEBUG: Nie udalo sie pobrac danych tematu: {info_err}")

                forum_writable = False
                for info in topic_infos:
                    if not info.get("thread_id"):
                        continue

                    topic_selector = f"a[data-thread-id='{info['thread_id']}']"
                    try:
                        topic_el = driver.find_element(By.CSS_SELECTOR, topic_selector)
                    except Exception as find_err:
                        print(f"    -> DEBUG: Nie znaleziono tematu {info['thread_id']} ponownie: {find_err}")
                        continue

                    topic_clicked = False
                    for attempt in range(3):
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", topic_el)
                        except Exception:
                            pass
                        try:
                            topic_el.click()
                            topic_clicked = True
                            break
                        except ElementClickInterceptedException:
                            print("    -> DEBUG: Klikniecie tematu przechwycone, ponawiam...")
                            time.sleep(0.3)
                            continue
                        except StaleElementReferenceException:
                            print("    -> DEBUG: Temat jest nieaktualny, odswiezam referencje...")
                            try:
                                topic_el = driver.find_element(By.CSS_SELECTOR, topic_selector)
                            except Exception:
                                break
                        except Exception as click_err:
                            print(f"    -> DEBUG: Blad klikniecia tematu {info['thread_id']}: {click_err}")
                            break
                    if not topic_clicked:
                        try:
                            driver.execute_script("arguments[0].click();", topic_el)
                            topic_clicked = True
                            print("    -> DEBUG: Klikniecie tematu wykonane przez JS.")
                        except Exception as js_err:
                            print(f"    -> DEBUG: Nie udalo sie kliknac tematu (JS): {js_err}")
                            continue

                    try:
                        WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@id='column-center']//div[contains(@class,'messages-container')]"))
                        )
                    except Exception:
                        time.sleep(0.5)

                    input_el = _find_message_input(driver, timeout=2)
                    if input_el:
                        try:
                            snippet = input_el.get_attribute("outerHTML") or ""
                            snippet = snippet.replace("\n", " ")[:120]
                        except Exception:
                            snippet = ""
                        display_name = info.get("name") or info["thread_id"]
                        writable_chats.append(
                            {
                                "name": f"{chat_name} / {display_name}",
                                "id": i,
                                "peer_id": peer_id,
                                "thread_id": info["thread_id"],
                            }
                        )
                        print(
                            f"  -> OK: Mozna pisac w podczacie '{display_name}' w grupie '{chat_name}'. [input: {snippet}]"
                        )
                        forum_writable = True
                    else:
                        print("    -> DEBUG: Brak pola tekstowego w tym podczacie.")

                    _go_back_from_topic(driver)
                    try:
                        WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-thread-id]"))
                        )
                    except Exception:
                        time.sleep(0.5)

                if forum_writable:
                    # sprobuj opuscic widok forum (powrot do listy czatow)
                    for _ in range(3):
                        remaining_topics = _find_topics(driver)
                        if not remaining_topics:
                            break
                        if not _go_back_from_topic(driver):
                            break
                        time.sleep(0.2)
                    continue
                else:
                    print("  -> DEBUG: Nie znaleziono pisalnego podczatu. Sprawdzam widok glowny...")
            else:
                candidates = driver.find_elements(By.XPATH, "//a[@data-thread-id]")
                print(f"  -> DEBUG: Brak widocznej listy tematow. Znaleziono globalnie {len(candidates)} elementow z data-thread-id.")
                for idx, cand in enumerate(candidates[:10]):
                    try:
                        cand_peer = cand.get_attribute("data-peer-id")
                        cand_tid = cand.get_attribute("data-thread-id")
                        cand_text = cand.text.strip() if cand.text else ""
                        print(f"    -> DEBUG candidate[{idx}]: peer={cand_peer} thread={cand_tid} text='{cand_text[:80]}'")
                    except Exception:
                        continue

            input_el = _find_message_input(driver, timeout=2)
            if input_el:
                try:
                    snippet = input_el.get_attribute("outerHTML") or ""
                    snippet = snippet.replace("\n", " ")[:120]
                except Exception:
                    snippet = ""
                writable_chats.append({"name": chat_name, "id": i, "peer_id": peer_id})
                print(f"  -> OK: Mozna pisac w '{chat_name}' [input: {snippet}]")
            else:
                print(f"  -> Info: Nie mozna pisac w '{chat_name}' (brak aktywnego pola tekstowego).")

        except Exception as e:
            print(f"  -> Blad podczas przetwarzania czatu: {e}")
            continue
    return writable_chats