# Bambu Lab A1 Pen Plotter - Guida del Progetto

Benvenuto nel progetto **Bambu Lab A1 Pen Plotter**!  
Questa cartella contiene l'intera suite software per convertire la stampante 3D **Bambu Lab A1** in un plotter per scrivere su fogli e quaderni reali (formato A4/A5 con rigatura italiana 1R da 8.0 mm) replicando fedelmente la calligrafia corsiva naturale dell'utente.

---

## 1. Struttura dei File e Moduli

* **`notebook_writer.py`**  
  Il motore principale della pipeline:
  * Impaginazione automatica del testo su righe di quaderno reali (preset `quaderno-1r`, `foglio-singolo`, `custom`).
  * Connessione corsiva fluida (ligature dirette senza sollevamenti o ponti orizzontali vuoti).
  * Humanizer con micro-variazioni realistiche (tremolio naturale della mano, inclinazione, pressione).
  * Generazione G-code ottimizzato con alzata penna rapida in Z.
  * Impacchettamento automatico nel container `.gcode.3mf` compatibile con Bambu Studio e stampa diretta da MicroSD.
  * Rendering visivo fotorealistico ad altissima risoluzione (PNG e SVG).

* **`extract_ipad_handwriting.py`**  
  Estrattore vettoriale per iPad:
  * Legge il PDF compilato su iPad con Apple Pencil (Goodnotes, Notability, Freeform, app File di iOS).
  * Estrae nativamente le curve matematiche di Bézier e i segmenti vettoriali tramite PyMuPDF (`fitz`).
  * Normalizza le coordinate rispetto alla linea di base in millimetri e aggiorna direttamente `fonts/my_handwriting.json`.

* **`upload_to_printer.py`**  
  Trasferimento wireless diretto alla stampante via FTPS implicito (porta 990):
  * IP Stampante: `192.168.1.25`
  * Porta: `990` (TLS implicito pre-banner)
  * Utente: `bblp`
  * Codice di accesso: `c044646f`
  * Carica il file `.gcode.3mf` direttamente sulla MicroSD della stampante pronto per essere avviato dal touchscreen.

* **`generate_alphabet_specimen.py`**  
  Genera la tabella analitica ad alta definizione (`anteprima_tabella_alfabeto.png`) con tutti i caratteri isolati in riquadri con guide di rigo e punti di attacco (verde) e stacco (rosso).

* **`optimize_font.py`** & **`vectorize_handwriting.py`**  
  Script per la pulizia geometrica, rimozione di pixel spuri, calcolo delle distanze di avanzamento (`advance_width`) e saldatura dei tratti.

* **Cartelle:**
  * `fonts/`: contiene il font attivo (`my_handwriting.json`) e il font corsivo di fallback (`default_cursive_stroke.json`).
  * `templates/`: modelli PDF di calibrazione, tra cui **`foglio_calibrazione_ipad.pdf`** e le sue specifiche `ipad_grid_spec.json`.
  * `input/`: file di testo da scrivere (es. `alfabeto_completo.txt`).
  * `output/`: G-code generati, pacchetti `.gcode.3mf`, anteprime fotorealistiche PNG e SVG.
  * `tests/`: 28 unit test automatizzati (`python -m unittest discover -s tests`).

---

## 2. Parametri Meccanici Verificati (Hardware A1)

* **Quota di Scrittura (Contatto Penna con Foglio)**:
  * Su foglio singolo fissato con magneti su piatto PEI: `Z = 1.8 mm`
  * Con quaderno/blocco notes: specificare spessore con `--thickness <mm>` o forzare con `--z-down 1.8`
* **Quota di Sicurezza / Spostamento (Pen UP)**:
  * `Z = 4.5 mm` - `6.0 mm` (corsa di disimpegno penna rapida)
* **Area di Stampa Utile**:
  * Piatto Bambu A1: $256 \times 256\text{ mm}$
  * Foglio A4 orizzontale / quaderno centrato nel piatto
* **Preset Quaderno 1R Italiano**:
  * Spaziatura righe: `8.0 mm`
  * Margine superiore: `32.0 mm`
  * Nessun rigo rosso verticale (standard 1R)
  * Inchiostro anteprima: Bic Cristal Blue (`#153675`)

---

## 3. Workflow Rapido

### Passo 1: Nuova Calligrafia da iPad (quando pronto il PDF)
1. Compila il modello **`templates/foglio_calibrazione_ipad.pdf`** sull'iPad con Apple Pencil.
2. Salva il file PDF esportato (es. in `templates/mio_ipad_compilato.pdf`).
3. Estrai la calligrafia vettoriale:
   ```powershell
   python extract_ipad_handwriting.py templates/mio_ipad_compilato.pdf fonts/my_handwriting.json
   ```

### Passo 2: Generazione Scrittura e Anteprima
Per scrivere un testo (da stringa o da file `.txt`):
```powershell
python notebook_writer.py --preset quaderno-1r --input input/alfabeto_completo.txt --z-down 1.8
```
Questo creerà:
* `output/pagina_quaderno.gcode`
* `output/pagina_quaderno.gcode.3mf`
* `output/anteprima_pagina.png`

### Passo 3: Invio Diretto alla Stampante 3D via Wi-Fi
```powershell
python upload_to_printer.py output/pagina_quaderno.gcode.3mf
```
Il file apparirà all'istante sullo schermo touch della Bambu Lab A1, pronto per la scrittura premendo "Stampa".
