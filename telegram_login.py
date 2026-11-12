"""Phone-number login for Telegram Web K, driven from the GUI (no QR code)."""
import time

from selenium.webdriver.common.keys import Keys

# Returns one of: logged_in, qr, phone, code, password, signup, loading
# plus the error text shown under an input field, if any.
_STATE_JS = r"""
const vis = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const err = [...document.querySelectorAll('.input-field.error label, .input-field.error .input-field-label')]
  .filter(vis).map(l => l.innerText.trim()).filter(Boolean).join('; ');
if (vis(document.querySelector('.input-search-input')) || vis(document.querySelector('#column-left .chatlist')))
  return ['logged_in', ''];
if (vis(document.querySelector('.input-field-phone .input-field-input'))) return ['phone', err];
if ([...document.querySelectorAll('input[type="password"]')].some(vis)) return ['password', err];
const other = [...document.querySelectorAll('.input-field-input, input[type="text"], input[type="tel"], input[inputmode="numeric"]')]
  .filter(vis)
  .filter(i => !i.closest('.input-field-phone') && !i.closest('.input-select'));
if (other.length === 1) return ['code', err];
if (other.length >= 2) return ['signup', err];
const qrBtn = [...document.querySelectorAll('button')].filter(vis)
  .find(b => /phone|telefon/i.test(b.innerText));
if (qrBtn || document.querySelector('canvas.qr-canvas, .qr-container')) return ['qr', err];
return ['loading', err];
"""


def get_state(driver):
    try:
        state, error = driver.execute_script(_STATE_JS)
        return state, error
    except Exception:
        return "loading", ""


def wait_for_state(driver, wanted, timeout=30, stop_event=None):
    """Wait until the page leaves 'loading' (and, if given, reaches one of `wanted`)."""
    end = time.time() + timeout
    state, error = "loading", ""
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            break
        state, error = get_state(driver)
        if state != "loading" and (not wanted or state in wanted or error):
            return state, error
        time.sleep(0.5)
    return state, error


def wait_for_change(driver, current, timeout=25):
    """Wait until the state differs from `current` or an error appears."""
    end = time.time() + timeout
    state, error = current, ""
    while time.time() < end:
        state, error = get_state(driver)
        if (state not in (current, "loading")) or error:
            return state, error
        time.sleep(0.5)
    return state, error


def _visible_input(driver, js_selector):
    return driver.execute_script(
        r"""
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
return [...document.querySelectorAll(arguments[0])].filter(vis)
  .filter(i => !i.closest('.input-field-phone') || arguments[0].includes('phone'))
  .filter(i => !i.closest('.input-select'))[0] || null;
""",
        js_selector,
    )


def _type_into(driver, element, text):
    element.click()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(Keys.BACKSPACE)
    element.send_keys(text)


def _click_primary(driver):
    driver.execute_script(
        r"""
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const b = [...document.querySelectorAll('button.btn-primary.btn-color-primary')].filter(vis)[0];
if (b) b.click();
"""
    )


def open_phone_form(driver):
    """From the QR page switch to the phone-number form."""
    driver.execute_script(
        r"""
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const b = [...document.querySelectorAll('button')].filter(vis).find(b => /phone|telefon/i.test(b.innerText));
if (b) b.click();
"""
    )
    return wait_for_state(driver, ("phone",), timeout=15)


def submit_phone(driver, phone):
    phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not phone.startswith("+"):
        phone = "+" + phone
    state, _ = get_state(driver)
    if state == "qr":
        state, _ = open_phone_form(driver)
    if state != "phone":
        return state, "Nie znaleziono formularza numeru telefonu."
    el = _visible_input(driver, ".input-field-phone .input-field-input")
    _type_into(driver, el, phone)
    time.sleep(0.8)
    _click_primary(driver)
    return wait_for_change(driver, "phone")


def submit_code(driver, code):
    code = "".join(ch for ch in code if ch.isdigit())
    el = _visible_input(
        driver, '.input-field-input, input[type="text"], input[type="tel"], input[inputmode="numeric"]'
    )
    if el is None:
        return get_state(driver)[0], "Nie znaleziono pola na kod."
    _type_into(driver, el, code)  # Telegram submits automatically once the code is complete
    time.sleep(1.0)
    state, error = get_state(driver)
    if state == "code" and not error:
        _click_primary(driver)
    return wait_for_change(driver, "code")


def submit_password(driver, password):
    el = _visible_input(driver, 'input[type="password"]')
    if el is None:
        return get_state(driver)[0], "Nie znaleziono pola na haslo."
    _type_into(driver, el, password)
    el.send_keys(Keys.ENTER)
    time.sleep(0.5)
    _click_primary(driver)
    return wait_for_change(driver, "password", timeout=30)
