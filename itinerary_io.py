"""
Fait le pont entre :
- un algorithme Processing "construction des itinéraires" (le vôtre) qui
  produit une couche/table (une ligne = un itinéraire potentiel),
- l'algorithme "optimisation" qui a besoin d'un ProblemData/WorkplaceProblemData.

Les champs hub_requirements et parking_demand (listes/dict imbriqués) sont
encodés en JSON dans des champs texte, car les couches QGIS ne stockent que
des types simples (String, Double, Int...). C'est le format le plus simple
à inspecter (ouvrir la table attributaire, voir le JSON en clair) et le plus
robuste pour chaîner deux algorithmes Processing, y compris dans un modèle
graphique (Processing > Modeleur).
"""



