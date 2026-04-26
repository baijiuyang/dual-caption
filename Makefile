# Run from repo root: `make` or `make all`
# Needs GNU make + bash (e.g. Git for Windows) on PATH.
.PHONY: all

all:
	@powershell -NoProfile -Command "$$bash='bash'; if (Test-Path 'C:\Program Files\Git\bin\bash.exe') { $$bash='C:\Program Files\Git\bin\bash.exe' } elseif (Test-Path 'C:\Program Files\Git\usr\bin\bash.exe') { $$bash='C:\Program Files\Git\usr\bin\bash.exe' }; & $$bash 'scripts/all.sh'"
