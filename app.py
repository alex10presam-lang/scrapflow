"""Servidor local. Execute: python app.py."""

from scrapflow import create_app

app = create_app()

if __name__ == "__main__":
    import argparse
    import threading
    import webbrowser

    parser = argparse.ArgumentParser(description="ScrapFlow local com fontes fictícias.")
    parser.add_argument("--open", action="store_true", help="Abrir o painel no navegador.")
    args = parser.parse_args()
    if args.open:
        threading.Timer(1, lambda: webbrowser.open("http://127.0.0.1:5050/#automation")).start()
    app.run(host="127.0.0.1", port=5050, debug=False)
