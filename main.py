from telegram_browser import start_browser, wait_for_login
from config import TELEGRAM_WEB_URL
from telegram_scan import scan_all_chats, filter_group_chats
from telegram_scheduler import run_scheduler


def main():
    print("Inicjalizacja sterownika przegladarki Chrome...")
    driver = start_browser()
    driver.get(TELEGRAM_WEB_URL)
    print("Otwieranie Telegram Web... Prosze zalogowac sie na swoje konto.")

    try:
        wait_for_login(driver)
        # Ustaw zoom na 30% aby zmieściło się więcej czatów!
        driver.execute_script("document.body.style.zoom='20%'")
        chats = scan_all_chats(driver)
        if not chats:
            print("Nie znaleziono zadnych czatow na liscie. Zamykanie.")
            return
        writable_chats = filter_group_chats(chats, driver)
        if not writable_chats:
            print("\nNie znaleziono zadnych kanalow ani grup, w ktorych mozna pisac.")
            return
        print("\n--- Znaleziono kanaly/grupy, w ktorych mozna pisac ---")
        for idx, chat_info in enumerate(writable_chats):
            print(f"{idx + 1}. {chat_info['name']}")
        print("----------------------------------------------------")
        choice = input("Podaj numery czatow do wyslania wiadomosci (np. 1,3,8) lub wpisz 'all', aby wyslac do wszystkich: ").lower()
        if choice == 'all':
            final_chats = writable_chats
        else:
            try:
                chosen_indices = [int(n.strip()) - 1 for n in choice.split(',')]
                final_chats = [writable_chats[i] for i in chosen_indices if 0 <= i < len(writable_chats)]
            except (ValueError, IndexError):
                print("Nieprawidlowy format.")
                return
        if final_chats:
            run_scheduler(driver, final_chats)
        else:
            print("\nNie wybrano zadnych czatow. Zamykanie programu.")
    except KeyboardInterrupt:
        print("\nProgram przerwany przez uzytkownika.")
    finally:
        print("Zamykanie przegladarki.")
        driver.quit()

if __name__ == "__main__":
    main()