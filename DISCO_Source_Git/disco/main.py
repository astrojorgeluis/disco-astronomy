import sys

def run():
    if len(sys.argv) > 1 and sys.argv[1].lower() == "gui":
        from disco.server import start_server
        start_server()
    else:
        from disco.cli import main
        main()

if __name__ == "__main__":
    run()