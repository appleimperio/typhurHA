# Typhur Bridge

Home Assistant add-on som kobler Typhur Sync Quad termometer direkte til Home Assistant via MQTT auto-discovery.

## Funksjon

Add-onen abonnerer på Typhur sin sky-MQTT (AWS IoT) og videresender temperaturdata til Home Assistant sin lokale MQTT-broker. Alle prober opprettes automatisk som sensorer i HA.

## Installasjon

1. Gå til **Innstillinger → Add-ons → Add-on butikk**
2. Trykk ⋮ → **Egendefinerte repositories**
3. Legg til: `https://github.com/oleost/typhurHA`
4. Finn **Typhur Bridge** og installer

## Konfigurasjon

| Felt | Beskrivelse |
|------|-------------|
| `typhur_token` | Auth-token fra Typhur API (se under) |
| `mqtt_host` | HA MQTT broker (standard: `core-mosquitto`) |
| `mqtt_port` | MQTT port (standard: `1883`) |
| `mqtt_username` | MQTT brukernavn (om påkrevd) |
| `mqtt_password` | MQTT passord (om påkrevd) |

## Hente Typhur token

Token hentes én gang og lagres. Se prosjektdokumentasjon for fremgangsmåte.

## Sensorer som opprettes

For hver probe opprettes:
- **Temperatur** (°C)
- **Omgivelsestemperatur** (°C)
- **Batteri** (%)
- **Status** (cooking/charging/idle)

For enheten:
- **Enhetsbatteri** (%)
- **WiFi Signal** (dBm)
