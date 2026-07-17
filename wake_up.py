from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

APP_URL = "https://capitalmas.streamlit.app"

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

try:
    print(f"Abriendo {APP_URL} ...")
    driver.get(APP_URL)
    time.sleep(15)  # le da tiempo a que cargue y establezca el WebSocket

    # Si aparece el botón de "wake up", lo clickea
    try:
        boton = driver.find_element("xpath", "//button[contains(text(), 'get this app back up')]")
        boton.click()
        print("Encontré el botón de reactivar, hice clic.")
        time.sleep(30)  # esperar que la app termine de levantar
    except Exception:
        print("La app ya estaba despierta, no había botón de reactivar.")

    print("Título de la página:", driver.title)

finally:
    driver.quit()
    print("Listo.")
