"""La versión HTML de los correos: botón para el enlace principal y nada de lo que
escribió otra persona interpretado como HTML."""
from consola.cuentas import CorreoEnCarpeta
from consola.correo_html import html_del_correo, texto_del_boton

URL = "https://consola.test"


def test_el_enlace_solo_en_su_parrafo_es_un_boton_con_respaldo():
    html = html_del_correo("Confirma tu correo", f"Hola:\n\nConfirma:\n\n{URL}/verificar?t=abc\n\nVence en 2 días.")

    assert f'href="{URL}/verificar?t=abc"' in html
    assert ">Confirmar mi correo</a>" in html
    assert "¿El botón no funciona?" in html
    assert "Vence en 2 días." in html


def test_una_frase_con_en_es_el_texto_del_boton_y_el_segundo_enlace_va_aparte():
    html = html_del_correo("Ya tienes cuenta",
                           f"Entra en {URL}/entrar\n¿No recuerdas la contraseña? Pide una nueva en {URL}/olvide")

    assert ">Entra</a>" in html
    assert "Pide una nueva &rarr;</a>" in html
    assert html.count("¿El botón no funciona?") == 1


def test_lo_que_escribio_un_comprador_no_se_interpreta():
    html = html_del_correo('Reserva <script>', 'Nombre: Ana <b>Pérez</b> "x"\n\nVer: ' + URL + "/#/reservas")

    assert "<b>Pérez</b>" not in html and "<script>" not in html
    assert "Ana &lt;b&gt;Pérez&lt;/b&gt;" in html
    assert "Reserva &lt;script&gt;" in html


def test_sin_enlaces_no_hay_boton():
    html = html_del_correo("Aviso", "Solo texto.\nOtra línea.")

    assert "¿El botón no funciona?" not in html
    assert "Solo texto.<br>Otra línea." in html


def test_el_boton_dice_adonde_lleva():
    assert texto_del_boton(f"{URL}/#/planos/mi-loteo") == "Abrir el loteo"
    assert texto_del_boton(f"{URL}/restablecer?t=1") == "Elegir contraseña nueva"
    assert texto_del_boton(f"{URL}/") == "Abrir la consola"


def test_el_buzon_del_qa_deja_el_html_al_lado(tmp_path):
    CorreoEnCarpeta(tmp_path).enviar("a@b.cl", "Hola", f"Entra en {URL}/entrar")

    [html] = tmp_path.glob("*.html")
    [json_] = tmp_path.glob("*.json")
    assert html.stem == json_.stem
    assert ">Entra</a>" in html.read_text()
