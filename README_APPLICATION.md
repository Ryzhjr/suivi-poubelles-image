# Application Wild Dump Prevention

Cette application realise la version obligatoire du projet :

- upload d'images ;
- extraction automatique de caracteristiques ;
- classification automatique par regles ;
- annotation manuelle clean / dirty ;
- stockage SQLite ;
- dashboard avec statistiques ;
- import du dataset fourni.

## Installation

Depuis le dossier du projet :

```bash
pip install -r requirements.txt
```

## Lancement

```bash
python app.py
```

Puis ouvrir :

```text
http://127.0.0.1:5000
```

## Utilisation

1. Ouvrir le dashboard.
2. Cliquer sur "Importer le dataset fourni" pour charger les images de `Data/`.
3. Aller dans "Images" pour consulter les images importees.
4. Ouvrir une image pour voir ses caracteristiques.
5. Annoter l'image avec `Clean` ou `Dirty`.
6. Revenir au dashboard pour voir les statistiques mises a jour.

## Donnees utilisees

- `Data/train/with_label/clean` : images propres deja annotees.
- `Data/train/with_label/dirty` : images sales deja annotees.
- `Data/train/no_label` : images sans annotation.
- `Data/test` : images de test.

## Caracteristiques extraites

Pour chaque image, l'application calcule :

- taille du fichier ;
- largeur ;
- hauteur ;
- couleur moyenne RGB ;
- luminosite moyenne ;
- contraste ;
- score simple de contours.

## Classification automatique

La version obligatoire n'utilise pas de machine learning.

Elle applique des regles conditionnelles simples :

- image sombre ;
- contraste eleve ;
- score de contours eleve ;
- fichier volumineux.

Selon le score obtenu, l'image est classee :

- `dirty` ;
- `clean` ;
- `unknown`.

## Base de donnees

La base SQLite est creee automatiquement dans :

```text
database.db
```

Les images importees ou uploadees sont copiees dans :

```text
uploads/
```

## Demo conseillee

1. Lancer l'application.
2. Importer le dataset.
3. Montrer le dashboard.
4. Ouvrir une image.
5. Montrer les caracteristiques extraites.
6. Modifier l'annotation manuelle.
7. Uploader une nouvelle image.
8. Revenir au dashboard.

