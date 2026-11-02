# Bambu Lab A1 - Calligraphic Pen Plotter Suite

Suite completa per trasformare la stampante 3D **Bambu Lab A1** in un pen plotter calligrafico che scrive su carta e quaderni reali con la calligrafia corsiva naturale dell'utente.

Consulta la guida dettagliata del progetto: **[PROJECT_GUIDE.md](PROJECT_GUIDE.md)**

## Avvio Rapido

### 1. Test Suite
```powershell
python -m unittest discover -s tests
```

### 2. Genera Scrittura su Quaderno 1R
```powershell
python notebook_writer.py --preset quaderno-1r --input input/alfabeto_completo.txt --z-down 1.8
```

### 3. Invia Wireless alla Stampante (MicroSD via FTPS)
```powershell
python upload_to_printer.py output/pagina_quaderno.gcode.3mf
```

### 4. Estrazione Calligrafia da iPad (PDF Apple Pencil)
```powershell
python extract_ipad_handwriting.py <percorso_pdf_ipad> fonts/my_handwriting.json
```
