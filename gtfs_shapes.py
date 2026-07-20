# -*- coding: utf-8 -*-
"""
Created on Wed Jul 15 09:41:09 2026

@author: eleonore.lagourgue
"""

import datetime
import partridge as ptg
import geopandas as gpd
import pandas as pd
import osmnx as ox
import networkx as nx
import pickle
from shapely.geometry import Point,MultiPoint, LineString
from shapely.ops import substring
import zipfile
import os
import io
import gc





def ajuster_segment(geom, point_ref, debut=True):
    if geom.geom_type != 'LineString':
        # Pas une ligne exploitable : on ne peut pas découper, on garde tel quel
        # ou on la remplace par une ligne droite minimale si besoin
        return geom
    dist = geom.project(point_ref)
    if debut:
        return substring(geom, dist, geom.length)
    else:
        return substring(geom, 0, dist)

def findnearestnodeonnearestedge(Gr, X, Y):
    """
    source : https://stackoverflow.com/questions/68257014/how-to-find-nearest-node-along-nearest-edge

    Parameters
    ----------
    Gr : graphe au format osmnx
    X : TYPE
        DESCRIPTION.
    Y : TYPE
        DESCRIPTION.

    Returns
    -------
    nodeid : TYPE
        DESCRIPTION.

    """

    edge,dist = ox.distance.nearest_edges(Gr, X,Y, return_dist=True)
    u, v, key = edge
    edge_data = Gr.edges[u, v, key]
    edge_geom = edge_data["geometry"]

    n1 = Gr.nodes[u]
    n2 = Gr.nodes[v]

    d1 = ox.distance.euclidean(Y,X, n1['y'], n1['x'])
    d2 = ox.distance.euclidean(Y,X, n2['y'], n2['x'])
    
    point = Point(X, Y)
    dist_along = edge_geom.project(point)

    if d1 < d2:
        nodeid = u
        autre_node= v
    else:
        nodeid = v
        autre_node= u
    
    node_point = Point(Gr.nodes[nodeid]['x'], Gr.nodes[nodeid]['y'])
    dist_node_on_edge = edge_geom.project(node_point)


    

    return nodeid, dist, edge_geom, dist_along, dist_node_on_edge

def generer_shapes_gtfs(
    gtfs_zip_path: str | Path,
    graphe_route: nx.MultiDiGraph,
    graphe_train: nx.MultiDiGraph,
    seuil_distance_max_route_m: float = 100.0,
    seuil_distance_max_train_m: float = 500.0,
    feedback: Optional[FeedbackLike] = None,
) -> GtfsShapesResult:
    pass