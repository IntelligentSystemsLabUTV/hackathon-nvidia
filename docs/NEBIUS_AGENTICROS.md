# Nebius + AgenticROS

Il primo flusso integrato usa AgenticROS come livello di accesso e sicurezza ROS,
e Nebius come livello decisionale:

```text
camera Gazebo -> AgenticROS snapshot -> modello vision Nebius
              -> descrizione testuale -> Nemotron con tool calling
              -> tool AgenticROS -> topic ROS -> Go2 simulato
```

Il modello di ragionamento sceglie i tool. AgenticROS esegue le operazioni ROS e
applica i limiti di sicurezza. Il modello vision non comanda direttamente il
robot: produce solamente una descrizione del frame.

## Avvio

Nel primo terminale avviare Gazebo:

```bash
cd ~/workspace
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py
```

Nel secondo terminale eseguire una richiesta singola:

```bash
cd ~/workspace
./scripts/run_nebius_agent.sh \
  "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."
```

La configurazione ROS usata dall'adapter è `config/agenticros.json`. Le variabili
Nebius sono lette da `.env`:

- `NEBIUS_API_KEY`
- `NEBIUS_BASE_URL`
- `NEBIUS_VISION_MODEL`
- `NEBIUS_REASONING_MODEL`
- `NEBIUS_AGENTICROS_TOOLS` (opzionale, elenco separato da virgole)

Per contenere la latenza, l'adapter espone a Nemotron solo quattro tool utili al
prototipo Gazebo invece dell'intero catalogo AgenticROS. Il tool di profondità
rimane escluso finché il relativo topic Gazebo non viene configurato. Un elenco diverso può
essere configurato con `NEBIUS_AGENTICROS_TOOLS`.

Il modello di ragionamento predefinito è `nvidia/Nemotron-3_5-Lightning`: nei
test con tool calling ha completato due turni in circa 2,7 secondi, mentre
`NVIDIA-Nemotron-3-Nano-30B-A3B` ha richiesto circa 30–40 secondi. Il modello
vision rimane `openbmb/MiniCPM-V-4_5`.

## Sequenza di sviluppo

1. Verificare acquisizione e descrizione di un singolo frame senza movimento.
2. Usare l'azione temporizzata `ros2_move_for`, che pubblica velocità limitata e
   attende più pubblicazioni di stop alla scadenza, anche in caso di errore.
3. Eseguire un solo ciclo osservazione -> decisione -> movimento -> stop.
4. Ripetere il ciclo con una frequenza bassa e un limite massimo di passi.
5. Sostituire l'azione diretta con Nav2 mapless quando il relativo stack sarà pronto.

In questa fase non va ancora avviato un ciclo autonomo continuo: prima devono
essere verificati snapshot, percezione e arresto temporizzato separatamente.

Prima dell'upload, ogni frame viene convertito in JPEG qualità 78 e ridotto entro
`768x432`, mantenendo le proporzioni. Il frame ROS originale può quindi essere
1920x1080, ma Nebius riceve la versione ridotta. La vision restituisce un JSON
con ostacoli, spazio libero, aperture, livello di confidenza e incertezze.
