.PHONY: run console test check install-tk clean help

# Launch the graphical process monitor
run:
	python3 main.py

# Display process information in the terminal
console:
	python3 main.py --console

# Run all automated tests
test:
	python3 -m unittest discover -s tests -v

# Check Python files for syntax errors
check:
	python3 -m compileall -q main.py backend gui tests

# Install Tkinter on Ubuntu/Debian
install-tk:
	sudo apt update
	sudo apt install -y python3-tk

# Remove generated Python cache files
clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# Display available commands
help:
	@echo "Available commands:"
	@echo "  make run        - Launch graphical application"
	@echo "  make console    - Run terminal process monitor"
	@echo "  make test       - Run automated tests"
	@echo "  make check      - Check Python syntax"
	@echo "  make install-tk - Install Tkinter on Ubuntu/Debian"
	@echo "  make clean      - Remove Python cache files"
	@echo "  make help       - Display this help"
