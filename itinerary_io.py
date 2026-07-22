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
import json
from qgis.core import QgsFields, QgsField, QgsFeature, QgsFeatureSink, QgsWkbTypes
from qgis.PyQt.QtCore import QVariant

from .optimization_model import (
    ProblemData, Itinerary, WorkplaceProblemData, WorkplaceItinerary,
)


# ---------------------------------------------------------------------
# Encodage : clé de tuple (l, m) -> chaîne "l|m" (JSON n'autorise que des
# clés de type string dans les objets)
# ---------------------------------------------------------------------

def _encode_hub_key(l, m):
    return f"{l}|{m}"


def _decode_hub_key(key):
    l, m = key.split("|", 1)
    return (l, m)


def _encode_hub_requirements(hub_requirements):
    return json.dumps([[l, m] for (l, m) in hub_requirements])


def _decode_hub_requirements(text):
    return [(l, m) for l, m in json.loads(text)]


def _encode_parking_demand(parking_demand):
    return json.dumps({_encode_hub_key(l, m): v for (l, m), v in parking_demand.items()})


def _decode_parking_demand(text):
    return {_decode_hub_key(k): v for k, v in json.loads(text).items()}


# ---------------------------------------------------------------------
# Modèle POI : Itinerary <-> features
# ---------------------------------------------------------------------

POI_ITINERARY_FIELDS = [
    ("id", QVariant.String),
    ("node", QVariant.String),
    ("poi_category", QVariant.String),
    ("travel_time", QVariant.Double),
    ("hub_requirements", QVariant.String),  # JSON
    ("parking_demand", QVariant.String),     # JSON
]


def make_poi_itinerary_fields():
    fields = QgsFields()
    for name, qtype in POI_ITINERARY_FIELDS:
        fields.append(QgsField(name, qtype))
    return fields


def write_poi_itineraries_to_sink(itineraries, sink):
    """
    À appeler dans votre algorithme de construction, à la place d'écrire
    des Itinerary directement : pour chaque itinéraire calculé, construisez
    une QgsFeature avec ces champs et ajoutez-la au sink (QgsProcessingParameterFeatureSink,
    de type NoGeometry si vous n'avez pas de géométrie pertinente à associer).
    """
    fields = make_poi_itinerary_fields()
    for it in itineraries:
        f = QgsFeature(fields)
        f.setAttributes([
            it.id, it.node, it.poi_category, it.travel_time,
            _encode_hub_requirements(it.hub_requirements),
            _encode_parking_demand(it.parking_demand),
        ])
        sink.addFeature(f, QgsFeatureSink.FastInsert)


def read_poi_itineraries_from_source(source):
    """
    À appeler dans l'algorithme d'optimisation : reconstruit la liste
    d'objets Itinerary à partir de la couche/table produite par votre
    algorithme de construction.
    """
    itineraries = []
    for f in source.getFeatures():
        itineraries.append(Itinerary(
            id=f["id"],
            node=f["node"],
            poi_category=f["poi_category"],
            travel_time=f["travel_time"],
            hub_requirements=_decode_hub_requirements(f["hub_requirements"]),
            parking_demand=_decode_parking_demand(f["parking_demand"]),
        ))
    return itineraries


def build_poi_problem_data(nodes_src, hubs_src, itineraries_src,
                             poi_categories, travel_time_threshold,
                             modes, fixed_cost_hub, fixed_cost_mode, budget,
                             node_id_field="id", node_pop_field="population",
                             hub_id_field="id"):
    """
    Assemble le ProblemData complet à partir :
    - de la couche NODES (population par nœud),
    - de la couche HUBS (liste des hubs candidats),
    - de la table ITINERARIES produite par votre algorithme (décodée ci-dessus).

    poi_categories, travel_time_threshold, modes, coûts et budget restent de
    simples paramètres Processing (pas besoin de les faire transiter par une
    couche : QgsProcessingParameterNumber/String/Matrix suffisent).
    """
    population = {f[node_id_field]: f[node_pop_field] for f in nodes_src.getFeatures()}
    hub_locations = [f[hub_id_field] for f in hubs_src.getFeatures()]
    itineraries = read_poi_itineraries_from_source(itineraries_src)

    return ProblemData(
        population=population,
        poi_categories=poi_categories,
        hub_locations=hub_locations,
        modes=modes,
        itineraries=itineraries,
        travel_time_threshold=travel_time_threshold,
        fixed_cost_hub=fixed_cost_hub,
        fixed_cost_mode=fixed_cost_mode,
        budget=budget,
    )


# ---------------------------------------------------------------------
# Modèle emplois : WorkplaceItinerary <-> features
# ---------------------------------------------------------------------

WP_ITINERARY_FIELDS = [
    ("id", QVariant.String),
    ("origin", QVariant.String),
    ("destination", QVariant.String),
    ("travel_time", QVariant.Double),
    ("ratio_car", QVariant.Double),
    ("hub_requirements", QVariant.String),  # JSON
    ("parking_demand", QVariant.String),     # JSON
]


def make_wp_itinerary_fields():
    fields = QgsFields()
    for name, qtype in WP_ITINERARY_FIELDS:
        fields.append(QgsField(name, qtype))
    return fields


def write_wp_itineraries_to_sink(itineraries, sink):
    fields = make_wp_itinerary_fields()
    for it in itineraries:
        f = QgsFeature(fields)
        f.setAttributes([
            it.id, it.origin, it.destination, it.travel_time, it.ratio_car,
            _encode_hub_requirements(it.hub_requirements),
            _encode_parking_demand(it.parking_demand),
        ])
        sink.addFeature(f, QgsFeatureSink.FastInsert)


def read_wp_itineraries_from_source(source):
    itineraries = []
    for f in source.getFeatures():
        itineraries.append(WorkplaceItinerary(
            id=f["id"],
            origin=f["origin"],
            destination=f["destination"],
            travel_time=f["travel_time"],
            ratio_car=f["ratio_car"],
            hub_requirements=_decode_hub_requirements(f["hub_requirements"]),
            parking_demand=_decode_parking_demand(f["parking_demand"]),
        ))
    return itineraries


def build_workplace_problem_data(hubs_src, itineraries_src, od_src,
                                    modes, fixed_cost_hub, fixed_cost_mode, budget,
                                    hub_id_field="id",
                                    od_origin_field="origin_id", od_dest_field="destination_id",
                                    od_volume_field="volume"):
    commuting_volume = {
        (f[od_origin_field], f[od_dest_field]): f[od_volume_field]
        for f in od_src.getFeatures()
    }
    hub_locations = [f[hub_id_field] for f in hubs_src.getFeatures()]
    itineraries = read_wp_itineraries_from_source(itineraries_src)

    return WorkplaceProblemData(
        commuting_volume=commuting_volume,
        hub_locations=hub_locations,
        modes=modes,
        itineraries=itineraries,
        fixed_cost_hub=fixed_cost_hub,
        fixed_cost_mode=fixed_cost_mode,
        budget=budget,
    )
