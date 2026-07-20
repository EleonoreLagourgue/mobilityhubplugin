# -*- coding: utf-8 -*-
"""
Created on Fri Jul 17 16:37:12 2026

@author: eleonore.lagourgue
"""
from qgis.core import (
    QgsVectorLayer,
    QgsFeature, QgsGeometry, QgsFields, QgsField,
    QgsWkbTypes, 
)
from qgis.PyQt.QtCore import QVariant



import geopandas as gpd
from shapely import wkt as shapely_wkt
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

    # IMPORTANT : triple_index() suppose des LineString simples
    # (g.coords[0], g.coords[-1]). Une couche avec des entités
    # MultiLineString ferait planter cette logique -> on éclate.
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