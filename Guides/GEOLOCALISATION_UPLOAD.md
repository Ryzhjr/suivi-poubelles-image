# Geolocalisation au moment de l'upload

## Objectif

La page d'upload permet a l'utilisateur d'ajouter une position GPS au signalement au moment ou il envoie une photo.

Cette geolocalisation reste optionnelle. L'utilisateur peut toujours saisir une adresse ou une zone manuellement dans le champ `Adresse ou zone`.

## Fonctionnement utilisateur

1. L'utilisateur choisit une image.
2. Il peut remplir `Adresse ou zone` manuellement.
3. Il peut cliquer sur `Utiliser ma position`.
4. Le navigateur demande l'autorisation d'acceder a sa position.
5. Si l'utilisateur accepte, l'application enregistre :
   - `latitude`
   - `longitude`
   - `location_accuracy`, en metres
6. L'utilisateur peut aussi choisir l'etat observe :
   - `Clean`
   - `Dirty`
   - `Non annotee`

## Fonctionnement technique

La page `templates/upload.html` utilise l'API JavaScript du navigateur :

```javascript
navigator.geolocation.getCurrentPosition(...)
```

Quand la position est obtenue, le JavaScript remplit trois champs caches du formulaire :

```html
<input id="latitude" name="latitude" type="hidden">
<input id="longitude" name="longitude" type="hidden">
<input id="location_accuracy" name="location_accuracy" type="hidden">
```

Au moment du POST `/upload`, Flask lit ces valeurs et les enregistre dans la table `images`.

Les colonnes ajoutees dans SQLite sont :

```text
location_address TEXT
latitude REAL
longitude REAL
location_accuracy REAL
```

## Fichiers modifies

- `app.py`
  - ajoute les colonnes GPS si elles n'existent pas encore
  - lit les champs `latitude`, `longitude`, `location_accuracy`
  - garde l'adresse manuelle dans `location_address`

- `templates/upload.html`
  - ajoute le bouton `Utiliser ma position`
  - ajoute les champs caches GPS
  - garde le champ manuel `Adresse ou zone`

- `templates/image_detail.html`
  - affiche l'adresse
  - affiche les coordonnees GPS si elles existent
  - affiche la precision GPS si elle existe

- `static/css/style.css`
  - ajoute le style de la ligne de geolocalisation

## Limites importantes

- L'utilisateur doit accepter l'autorisation de localisation.
- Sur ordinateur, la position peut etre approximative.
- Sur telephone, la position est souvent plus precise.
- En production, la geolocalisation navigateur demande normalement HTTPS.
- En local, `http://127.0.0.1` ou `localhost` est accepte par la plupart des navigateurs.
- Si l'utilisateur refuse la localisation, l'upload reste possible avec l'adresse manuelle.

## Commande de lancement

Depuis le terminal VS Code :

```powershell
Set-Location "C:\Users\erwan\Downloads\Solution_Factory_Data-main\Solution_Factory_Data-main"; & "C:\Users\erwan\AppData\Local\Programs\Python\Python313\python.exe" app.py
```

Puis ouvrir :

```text
http://127.0.0.1:5001/upload
```
