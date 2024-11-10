# Trading Bot

Un bot de trading simple utilisant l'API Bitget.

## Installation

```bash
# 1. Cloner le repository
git clone <votre-repo-url>
cd <nom-du-dossier>

# 2. Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Sur Windows : venv\Scripts\activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditez ensuite le fichier .env avec vos informations d'API

## Configuration

Modifiez le fichier `config.py` pour ajuster les paramètres de trading selon vos besoins.

## Utilisation

```bash
python main.py
```

## Logs

Les logs sont écrits dans `trading_bot.log` et affichés dans la console.