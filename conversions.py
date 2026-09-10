# -*- coding: utf-8 -*-
"""
Created on Fri Jul 17 16:37:12 2026

@author: eleonore.lagourgue
"""
from qgis.core import (
    QgsVectorLayer,
    QgsFeature, QgsGeometry, QgsFields, QgsField,
    QgsWkbTypes, QgsFeatureSink,
    QgsVectorFileWriter, QgsProject,
)
from qgis.PyQt.QtCore import QVariant

import json

from .optimization_model import (
    ProblemData, Itinerary, WorkplaceProblemData, WorkplaceItinerary,
)

import pandas as pd
import geopandas as gpd
from shapely import wkt as shapely_wkt
import pyogrio
import os
import tempfile
import pyarrow as pa
#%%

	
def gdf_from_layer_arrow(layer):
    # SDSL2025 version
    with tempfile.TemporaryDirectory() as tmpdirname:
        path = os.path.join(tmpdirname, "data.arrow")
 
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile 
        options.layerName = 'data'
        options.driverName = "arrow"
        options.layerOptions = ['GEOMETRY_ENCODING=GEOARROW']  # tentative
         
       
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), options
    )
        if result[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Écriture échouée : {result}")
        print(os.path.getsize(path))
        try:
            with pa.memory_map(path, 'r') as source:
                table = pa.ipc.open_file(source).read_all()
        except pa.lib.ArrowInvalid:
            # au cas où ce serait plutôt du format "stream"
            with pa.memory_map(path, 'r') as source:
                table = pa.ipc.open_stream(source).read_all()

        gdf = gpd.GeoDataFrame.from_arrow(table)
        if gdf.crs is None:
            gdf = gdf.set_crs(layer.crs().authid(), allow_override=True)
    return gdf

def qgis_layer_to_gdf(layer: QgsVectorLayer) -> gpd.GeoDataFrame:
    """Convertit une QgsVectorLayer en GeoDataFrame."""
    # df = pd.DataFrame([feat.attributes() for feat in layer.getFeatures()],
    #               columns=[field.name() for field in layer.fields()])
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
#%%GTFS
def seconds_to_hms(val):
    """Reconvertit les secondes (format interne Partridge) en HH:MM:SS 
    pour pouvoir les relire ensuite."""
    if pd.isna(val) or val == "":
        return val
    try:
        total_seconds = int(float(val))
    except (ValueError, TypeError):
        return val  # déjà une chaîne HH:MM:SS ou valeur non numérique
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
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

def get_available_modes(feedback, itineraries_src, extra_modes=None):
    """
    Parcourt la table d'itinéraires et extrait l'ensemble des modes
    effectivement utilisés dans hub_requirements (ex: 'bs', 'cs').


    - extra_modes : modes à toujours inclure même s'ils n'apparaissent pas
      dans hub_requirements (ex: 'pt', car les itinéraires 100% transport
      public n'ont pas de hub_requirements et n'apparaîtraient donc jamais
      ici, alors qu'ils comptent quand même comme mode disponible).
    """
    modes = set()
    for f in itineraries_src.getFeatures():
        #feedback.pushInfo(f["hubs_required"])
        hubs_required = f["hubs_required"]
        if isinstance(hubs_required, str):
            hubs_required = json.loads(hubs_required)
        for couple in hubs_required:
            #feedback.pushInfo(str(couple))

            l,m= couple
            modes.add(m)
    if extra_modes:
        modes.update(extra_modes)
    return sorted(modes)

#%%POI
# ---------------------------------------------------------------------
# Modèle POI : Itinerary <-> features
# ---------------------------------------------------------------------

POI_ITINERARY_FIELDS = [
    ("id", QVariant.String),
    ("node", QVariant.String),
    ("poi_category", QVariant.String),
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
    Permet de passer d'une class Itinerary à un QgsFeature à ajouter au sink
    de type NoGeometry 
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





def read_poi_itineraries_from_source(source):
    """
    À appeler dans l'algorithme d'optimisation : reconstruit la liste
    d'objets Itinerary à partir de la couche/table produite par votre
    algorithme de construction.
    """
    itineraries = []
    for f in source.getFeatures():
        travel_time = f["travel_time"]
        if isinstance(travel_time, QVariant):
            if travel_time.isNull():
                travel_time = 0.0
            else:
                travel_time = travel_time.value()
            
        itineraries.append(Itinerary(
            id=f["id"],
            node=f["node"],
            poi_category=f["poi_category"],
            travel_time=float(travel_time),
            hubs_required=_decode_hub_requirements(f["hubs_required"]),
            parking_demand=_decode_parking_demand(f["parking_demand"]),
        ))
    return itineraries

def build_poi_problem_data(feedback,nodes_src, hubs_src, itineraries_src,pois_src,
                             poi_categories, travel_time_threshold,
                             modes=None, fixed_cost_hub=1000.0, fixed_cost_mode=None, budget=0,
                             node_id_field="id", node_pop_field="population",
                             hub_id_field="id", dest_id_field = "id"):
    """
    Assemble le ProblemData complet à partir :
    - de la couche NODES (population par nœud),
    - de la couche HUBS (liste des hubs candidats),
    - de la table ITINERARIES produite par votre algorithme (décodée ci-dessus).

    poi_categories, travel_time_threshold, modes, coûts et budget restent de
    simples paramètres Processing (pas besoin de les faire transiter par une
    couche : QgsProcessingParameterNumber/String/Matrix suffisent).
    """
    population = {f"pop_{f[node_id_field]}": f[node_pop_field] for f in nodes_src.getFeatures()}
    hub_locations = [f"hub_{f[hub_id_field]}" for f in hubs_src.getFeatures()]
    node = [f"pop_{f[node_id_field]}" for f in nodes_src.getFeatures()]
    dest = [f"dest_{f[dest_id_field]}" for f in pois_src.getFeatures()]

    hub_locations.extend(node)
    hub_locations.extend(dest)
    print("Ajout destinations et départs aux hubs")
    
    



    if modes is None:
        modes = get_available_modes(feedback,itineraries_src, extra_modes=["pt"])
    fixed_cost_mode = fixed_cost_mode or {}
    fixed_cost_mode = {m: fixed_cost_mode.get(m, 0.0) for m in modes}
    
    itineraries = read_poi_itineraries_from_source(itineraries_src)
    
    big_m = {}
    for p in poi_categories:
        threshold = travel_time_threshold[p]
        if threshold is None:
            feedback.pushWarning(f"Pas de seuil pour la catégorie '{p}'.")
            continue
        
        itin_p = [it for it in itineraries if it.poi_category == p]
        if not itin_p:
            big_m[p] = 1.0  # aucune contrainte réelle, valeur neutre
            continue
        
        max_gap = float(max(it.travel_time - threshold for it in itin_p))
        big_m[p] = max_gap * 1.01 if max_gap > 0 else 1.0
        
        feedback.pushInfo(f"big-M[{p}] = {big_m[p]:.2f}")
    
    hub_or_node_refs_in_itineraries = {
    l for it in itineraries for (l, m) in it.hubs_required
    }
    
    node_ids_from_nodes_src = {f"pop_{f[node_id_field]}" for f in nodes_src.getFeatures()}
    dest_ids_from_nodes_src = {f"pop_{f[dest_id_field]}" for f in pois_src.getFeatures()}

    missing = hub_or_node_refs_in_itineraries - set(hub_locations) - node_ids_from_nodes_src
    feedback.pushInfo(f"Références manquantes dans hub_locations : {missing}")
    missing = hub_or_node_refs_in_itineraries - set(hub_locations) - dest_ids_from_nodes_src
    feedback.pushInfo(f"Références manquantes dans hub_locations : {missing}")


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
        big_m = big_m
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


def read_wp_itineraries_from_source(feedback,source):
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


def build_workplace_problem_data(feedback,hubs_src, itineraries_src,nodes_src, od_gdf,
                                    modes=None, fixed_cost_hub=1000.0, fixed_cost_mode=None, budget=0,
                                    hub_id_field="fid",node_id_field="code_insee",
                                    od_origin_field="origine_id", od_dest_field="destination_id",
                                    od_volume_field="volume"):
    #A mettre en paramètres
    od_gdf[od_origin_field] = "pop_" + od_gdf[od_origin_field].astype(str)
    od_gdf[od_dest_field] = "pop_" + od_gdf[od_dest_field].astype(str)


    commuting_volume = dict(zip(
    zip(od_gdf[od_origin_field], od_gdf[od_dest_field]),
    od_gdf[od_volume_field]
    ))
    if modes is None:
        modes = get_available_modes(feedback,itineraries_src, extra_modes=["pt"])
    fixed_cost_mode = fixed_cost_mode or {}
    fixed_cost_mode = {m: fixed_cost_mode.get(m, 0.0) for m in modes}
    hub_locations = [f"hub_{f[hub_id_field]}" for f in hubs_src.getFeatures()]

    node = [f"pop_{f[node_id_field]}" for f in nodes_src.getFeatures()]
   
    
    itineraries = read_wp_itineraries_from_source(feedback,itineraries_src)
    hub_locations.extend(node)
    
    node_ids_from_nodes_src = {f"pop_{f[node_id_field]}" for f in nodes_src.getFeatures()}
    hub_or_node_refs_in_itineraries = {
    l for it in itineraries for (l, m) in it.hubs_required
    }
    missing = hub_or_node_refs_in_itineraries - set(hub_locations) - node_ids_from_nodes_src
    feedback.pushInfo(f"Références manquantes dans hub_locations : {missing}")


    return WorkplaceProblemData(
        commuting_volume=commuting_volume,
        hub_locations=hub_locations,
        modes=modes,
        itineraries=itineraries,
        fixed_cost_hub=fixed_cost_hub,
        fixed_cost_mode=fixed_cost_mode,
        budget=budget,
    )




