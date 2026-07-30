# -*- coding: utf-8 -*-
"""
Created on Fri Jul 17 16:37:12 2026

@author: eleonore.lagourgue
"""
from qgis.core import (
    QgsVectorLayer,
    QgsFeature, QgsGeometry, QgsFields, QgsField,
    QgsWkbTypes, QgsFeatureSink,
)
from qgis.PyQt.QtCore import QVariant

import json

from .optimization_model import (
    ProblemData, Itinerary, WorkplaceProblemData, WorkplaceItinerary,
)


import geopandas as gpd
from shapely import wkt as shapely_wkt

#%%
def qgis_layer_to_gdf(layer: QgsVectorLayer) -> gpd.GeoDataFrame:
    """Convertit une QgsVectorLayer (n'importe quelle source : shapefile,
    gpkg, couche mémoire, couche filtrée...) en GeoDataFrame."""
    if layer is None or not layer.isValid():
        raise ValueError("Couche QGIS invalide ou introuvable.")

    crs = layer.crs().authid()  # ex: 'EPSG:2154'
    fields = [f.name() for f in layer.fields()]
    records = []

    for feature in layer.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue

        attrs = {f: feature[f] for f in fields}
        attrs["geometry"] = shapely_wkt.loads(geom.asWkt())
        records.append(attrs)

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

    #On explose les géométries multiples
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)

    return gdf

def gdf_geom_to_qgs_wkbtype(gdf):
    """Déduit le type de géométrie QGIS à partir du GeoDataFrame."""
    geom_type = gdf.geom_type.iloc[0]  # ex: 'LineString', 'Point', 'Polygon'
    mapping = {
        "Point": QgsWkbTypes.Point,
        "LineString": QgsWkbTypes.LineString,
        "Polygon": QgsWkbTypes.Polygon,
        "MultiPoint": QgsWkbTypes.MultiPoint,
        "MultiLineString": QgsWkbTypes.MultiLineString,
        "MultiPolygon": QgsWkbTypes.MultiPolygon,
    }
    return mapping.get(geom_type, QgsWkbTypes.Unknown)


def gdf_to_qgsfields(gdf):
    """Construit un QgsFields à partir des colonnes non-géométrie du gdf."""
    fields = QgsFields()
    dtype_mapping = {
        "int64": QVariant.LongLong,
        "int32": QVariant.Int,
        "float64": QVariant.Double,
        "float32": QVariant.Double,
        "bool": QVariant.Bool,
        "object": QVariant.String,
        "datetime64[ns]": QVariant.DateTime,
    }
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        dtype_str = str(gdf[col].dtype)
        qtype = dtype_mapping.get(dtype_str, QVariant.String)
        fields.append(QgsField(col, qtype))
    return fields


def write_gdf_to_sink(gdf, sink):
    """Écrit chaque ligne du GeoDataFrame comme entité dans le sink."""
    geom_col = gdf.geometry.name
    attr_cols = [c for c in gdf.columns if c != geom_col]

    for _, row in gdf.iterrows():
        feat = QgsFeature()
        geom = QgsGeometry.fromWkt(row[geom_col].wkt)
        feat.setGeometry(geom)

        attrs = []
        for col in attr_cols:
            val = row[col]
            # Cast des types non supportés nativement par QVariant
            if hasattr(val, "item"):  # numpy scalar -> python natif
                val = val.item()
            attrs.append(val)
        feat.setAttributes(attrs)

        sink.addFeature(feat)

#%%
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
    return json.dumps([[l,m] for (l,m) in hub_requirements])


def _decode_hub_requirements(text):
    return [(l, m) for l, m in json.loads(text)]


def _encode_parking_demand(parking_demand):
    return json.dumps({_encode_hub_key(l, m): v for (l, m), v in parking_demand.items()})


def _decode_parking_demand(text):
    return {_decode_hub_key(k): v for k, v in json.loads(text).items()}

#%%POI
# ---------------------------------------------------------------------
# Modèle POI : Itinerary <-> features
# ---------------------------------------------------------------------

POI_ITINERARY_FIELDS = [
    ("id", QVariant.String),
    ("node", QVariant.String),
    ("poi_category", QVariant.String),
    ("mode_seq", QVariant.String),
    ("travel_time", QVariant.Double),
    ("hubs_required", QVariant.String), 
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
            _encode_hub_requirements(it.hubs_required),
            _encode_parking_demand(it.parking_demand),
        ])
        sink.addFeature(f, QgsFeatureSink.FastInsert)




def get_available_modes(itineraries_src, extra_modes=None):
    """
    Parcourt la table d'itinéraires et extrait l'ensemble des modes
    effectivement utilisés dans hub_requirements (ex: 'bs', 'cs').

    À utiliser à la place d'une liste de modes codée en dur : le modèle
    n'a besoin de créer des variables y_lm/u_lm que pour les modes qui
    apparaissent réellement dans au moins un itinéraire potentiel.

    - extra_modes : modes à toujours inclure même s'ils n'apparaissent pas
      dans hub_requirements (ex: 'pt', car les itinéraires 100% transport
      public n'ont pas de hub_requirements et n'apparaîtraient donc jamais
      ici, alors qu'ils comptent quand même comme mode disponible).
    """
    modes = set()
    for f in itineraries_src.getFeatures():
        for  m in (f["mode_seq"]):
            modes.add(m)
    if extra_modes:
        modes.update(extra_modes)
    return sorted(modes)


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
            hubs_required=_decode_hub_requirements(f["hubs_required"]),
            parking_demand=_decode_parking_demand(f["parking_demand"]),
        ))
    return itineraries

def build_poi_problem_data(nodes_src, hubs_src, itineraries_src,
                             poi_categories, travel_time_threshold,
                             modes=None, fixed_cost_hub=1000.0, fixed_cost_mode=None, budget=0,
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
    if modes is None:
        modes = get_available_modes(itineraries_src, extra_modes=["pt"])
    fixed_cost_mode = fixed_cost_mode or {}
    fixed_cost_mode = {m: fixed_cost_mode.get(m, 0.0) for m in modes}
    
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

#%%WP
# ---------------------------------------------------------------------
# Modèle emplois : WorkplaceItinerary <-> features
# ---------------------------------------------------------------------

WP_ITINERARY_FIELDS = [
    ("id", QVariant.String),
    ("origin", QVariant.String),
    ("destination", QVariant.String),
    ("travel_time", QVariant.Double),
    ("ratio_car", QVariant.Double),
    ("hubs_required", QVariant.String),  # JSON
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
            _encode_hub_requirements(it.hubs_required),
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
            hubs_required=_decode_hub_requirements(f["hubs_required"]),
            parking_demand=_decode_parking_demand(f["parking_demand"]),
        ))
    return itineraries


def build_workplace_problem_data(hubs_src, itineraries_src, od_gdf,
                                    modes=None, fixed_cost_hub=1000.0, fixed_cost_mode=None, budget=0,
                                    hub_id_field="fid",
                                    od_origin_field="origine_id", od_dest_field="destination_id",
                                    od_volume_field="volume"):
    #A mettre en paramètres
    
    commuting_volume = dict(zip(
    zip(od_gdf[od_origin_field], od_gdf[od_dest_field]),
    od_gdf[od_volume_field]
    ))
    if modes is None:
        modes = get_available_modes(itineraries_src, extra_modes=["pt"])
    fixed_cost_mode = fixed_cost_mode or {}
    fixed_cost_mode = {m: fixed_cost_mode.get(m, 0.0) for m in modes}
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




