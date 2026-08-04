# -*- coding: utf-8 -*-
"""
Created on Mon May 11 15:16:47 2026

@author: eleonore.lagourgue
"""
import networkx as nx
import  numpy as np
import osmnx as ox
import geopandas as gpd
import pandas as pd
# import shapely
from shapely import Point, MultiPoint, LineString, MultiLineString
# from shapely.ops import split, snap, unary_union
import matplotlib.pyplot as plt
import re
#import scipy
from scipy.spatial import KDTree
import sqlalchemy
#%%Création graphe
def safe_key(coord):
    return f"{coord[0]:.3f}, {coord[1]:.3f}"

def triple_index(route):
    all_keys = pd.concat([
        route.geometry.apply(lambda g: safe_key(g.coords[0])),
        route.geometry.apply(lambda g: safe_key(g.coords[-1]))
    ]).drop_duplicates().reset_index(drop=True)

    #Création du référentiel des noeuds uniques
    # On crée une clé texte "x, y" pour identifier chaque intersection physique
    nodes_ref = pd.DataFrame({"node_key": all_keys})
    nodes_ref["node_id"] = nodes_ref.index  # Notre futur osmid

    #Préparation des route avec leurs clés de début et fin
    route["start_key"] = route.geometry.apply(lambda g:safe_key(g.coords[0]))
    route["end_key"] = route.geometry.apply(lambda g:safe_key(g.coords[-1]))

    #Jointures pour récupérer les id de noeuds
    # u : départ
    route = route.merge(nodes_ref[['node_key', 'node_id']], left_on="start_key", right_on="node_key", how="left")
    route = route.rename(columns={"node_id": "u"}).drop(columns="node_key")

    # v : arrivée
    route = route.merge(nodes_ref[['node_key', 'node_id']], left_on="end_key", right_on="node_key", how="left")
    route = route.rename(columns={"node_id": "v"}).drop(columns="node_key")

    route = route.drop_duplicates(subset=["u", "v", "geometry"])
    route["osmid"] = f"999{route["u"]}{route['v']}"
    
    print(route["u"])
    mask = route["u"].isna()
    #print(route.loc[mask, "start_key"].head(10))
    print(nodes_ref["node_key"].head(10))

    route= route.assign(key = 0)
    return route
def sens_circulation (route, colonne_sens, direct, inverse, double, autre):
    """
    Parameters
    ----------
    route : TYPE
        DESCRIPTION.
    colonne_sens : TYPE string
        DESCRIPTION.
    direct : TYPE string
        DESCRIPTION.
    inverse : TYPE string
        DESCRIPTION.
    double : TYPE string
        DESCRIPTION.
    autre : TYPE
        DESCRIPTION.
    Returns
    -------
    None.
    """
    sens_direct = pd.DataFrame(columns=route.columns)
    sens_inverse = pd.DataFrame(columns=route.columns)
    double_uv_so = pd.DataFrame(columns=route.columns)
    double_vu_so = pd.DataFrame(columns=route.columns)

    #Permet de gérer les différences de nom de la colonne de géométrie
    if "geometry" in route.columns:
        geom = "geometry"
    elif "geom" in route.columns:
        geom = "geom"
        
        
    if colonne_sens:
        print(colonne_sens)
        if direct:
            #On vérifie que la chaîne de caractères n'est pas vide
            sens_direct  = route[route[colonne_sens] == direct].copy()
        if inverse:
            #Idem que pour direct
            #Sens inverse : on échange u et v + on inverse la géométrie
            sens_inverse = route[route[colonne_sens] == inverse].copy()
            sens_inverse[["u", "v"]] = sens_inverse[["v", "u"]].values
            sens_inverse[geom] = sens_inverse[geom].apply(
                lambda g: LineString(list(g.coords)[::-1])
            )
        if autre:
            #Idem pour sans objet
            double_uv_so = route[route[colonne_sens].isin(autre)].copy()
            double_vu_so  = double_uv_so.copy()
            double_vu_so[["u", "v"]] = double_vu_so[["v", "u"]].values
            double_vu_so[geom] = double_vu_so[geom].apply(
                lambda g: LineString(list(g.coords)[::-1])
            )
        if double:
            #Double sens : construction des deux arêtes u vers v et v vers u
            double_uv = route[route[colonne_sens] == double].copy()
            double_vu  = double_uv.copy()
            double_vu[["u", "v"]] = double_vu[["v", "u"]].values
            double_vu[geom] = double_vu[geom].apply(
                lambda g: LineString(list(g.coords)[::-1])
            )
    else:
        print("Pas de sens précisé")
        double_uv = route.copy()
        double_vu  = double_uv.copy()
        double_vu[["u", "v"]] = double_vu[["v", "u"]].values
        double_vu[geom] = double_vu[geom].apply(
            lambda g: LineString(list(g.coords)[::-1])
        )
       
        
    #Concaténation
    route_orientee = pd.concat(
        [sens_direct, sens_inverse, double_uv, double_vu, double_uv_so, double_vu_so],
        ignore_index=True
    )
    route_orientee = gpd.GeoDataFrame(route_orientee,geometry="geometry",crs=route.crs)


    route_orientee = route_orientee.drop_duplicates(subset=["u", "v", "geometry"])


    #Recalcul de key pour éviter les doublons (u, v, key)
    route_orientee["key"] = route_orientee.groupby(["u", "v"]).cumcount()

    #Réindexation finale
    route_orientee = route_orientee.set_index(["u", "v", "key"])
    
        
    return route_orientee

def sens_circulation_velo(route, colonne_sens, direct, inverse, double, autre, 
                          colonne_autre,
                          sens_velo_direct = None,
                          sens_velo_inverse = None,
                          double_sens_velo =None):
    columns = route.columns
    if "geom"  in columns:
        geometry= "geom"
    else:
        geometry = "geometry"
    
    empty = route.iloc[0:0].copy()  #DataFrame vide avec les mêmes colonnes
    sens_direct = empty
    sens_inverse = empty
    double_uv_so = empty
    double_vu_so = empty
    sens_direct_velo = empty
    sens_inverse_velo = empty

    if direct:
        #On vérifie que la chaîne de caractères n'est pas vide
        sens_direct  = route[route[colonne_sens] == direct].copy()
    if inverse:
        #Idem que pour direct
        #Sens inverse : on échange u et v + on inverse la géométrie
        sens_inverse = route[route[colonne_sens] == inverse].copy()
        sens_inverse[["u", "v"]] = sens_inverse[["v", "u"]].values
        sens_inverse[geometry] = sens_inverse[geometry].apply(
            lambda g: LineString(list(g.coords)[::-1])
        )

    #Double sens : construction des deux arêtes u vers v et v vers u
    double_uv = route.copy()
    double_vu  = double_uv.copy()
    double_vu[["u", "v"]] = double_vu[["v", "u"]].values
    double_vu[geometry] = double_vu[geometry].apply(
        lambda g: LineString(list(g.coords)[::-1])
    )
    if autre:
        #Idem pour sans objet
        double_uv_so = route[route[colonne_sens].isin(autre)].copy()
        double_vu_so  = double_uv_so.copy()
        double_vu_so[["u", "v"]] = double_vu_so[["v", "u"]].values
        double_vu_so[geometry] = double_vu_so[geometry].apply(
            lambda g: LineString(list(g.coords)[::-1])
        )
    if sens_velo_direct:
        #On vérifie que la chaîne de caractères n'est pas vide
        sens_direct_velo  = route[route[colonne_sens] == sens_velo_direct].copy()
    if sens_velo_inverse:
        #Idem que pour direct
        #Sens inverse : on échange u et v + on inverse la géométrie
        sens_inverse_velo = route[route[colonne_sens] == sens_velo_inverse].copy()
        sens_inverse_velo[["u", "v"]] = sens_inverse_velo[["v", "u"]].values
        sens_inverse_velo[geometry] = sens_inverse_velo[geometry].apply(
            lambda g: LineString(list(g.coords)[::-1])
        )
    #Concaténation
    route_orientee = pd.concat(
        [sens_direct, sens_inverse, double_uv, double_vu, double_uv_so, double_vu_so],
        ignore_index=True
    )


    route_orientee = route_orientee.drop_duplicates(subset=["u", "v", geometry])


    #Recalcul de key pour éviter les doublons (u, v, key)
    route_orientee["key"] = route_orientee.groupby(["u", "v"]).cumcount()

    #Réindexation finale
    route_orientee = route_orientee.set_index(["u", "v", "key"])
    return route_orientee
    

def table_noeuds(route):
    route_temp = route.reset_index()

    u_coords = route_temp[['u', 'start_key']].rename(columns={'u': 'osmid', 'start_key': 'key'})
    v_coords = route_temp[['v', 'end_key']].rename(columns={'v': 'osmid', 'end_key': 'key'})

    # Nettoyage des données pour enlever les doublons
    nodes_data = pd.concat([u_coords, v_coords])
    nodes_data = nodes_data.drop_duplicates(subset='osmid')

    #Table des noeuds
    gdf_nodes = gpd.GeoDataFrame(
        nodes_data, 
        geometry=nodes_data['key'].apply(lambda k: Point(float(k.split(',')[0]), float(k.split(',')[1]))),
        crs=route.crs
    )
    gdf_nodes = gdf_nodes.set_index('osmid')
    gdf_nodes['x'] = gdf_nodes.geometry.x
    gdf_nodes['y'] = gdf_nodes.geometry.y
    gdf_nodes = gdf_nodes.drop(columns=['key'])
    
    return gdf_nodes

def crea_graphe(route , colonne_sens = None,
                direct = None, inverse = None, 
                double=None, autre = None, 
                mode ="walk", 
                colonne_sens_velo =None,
                sens_velo_direct = None,
                sens_velo_inverse = None,
                double_sens_velo = None):
    """
    Fonction pour passer d'un geodataframe à un graphe
    sous forme OSMnX
    Permet l'utilisation de certaines bibliothèques dépendant de NetworkX et OSMnX

    Parameters
    ----------
    route : TYPE
        DESCRIPTION.
    colonne_sens : TYPE
        DESCRIPTION.
    direct : TYPE
        DESCRIPTION.
    inverse : TYPE
        DESCRIPTION.
    double : TYPE
        DESCRIPTION.
    autre : TYPE
        DESCRIPTION.
    mode : permet de préciser de quel mode
    de transport il s'agit

    Returns
    -------
    reseau_routier : TYPE
        DESCRIPTION.

    """
    
    route = triple_index(route)
    if mode == "drive":
        route_orientee = sens_circulation (route, colonne_sens, direct, inverse, double, autre)
    if mode == "walk":
        autre_walk =[direct, inverse]
        if autre == None:
            pass
        else:
            autre_walk.extend(autre)
        route_orientee = sens_circulation(route,colonne_sens, "", "", double, autre_walk)
    if mode == "bike":
        route_orientee =sens_circulation_velo(route, colonne_sens, 
                                              direct, inverse, double, autre, 
                                              colonne_sens_velo)
    if mode == "train":
        
        route_orientee = sens_circulation(route,colonne_sens, direct, inverse, double, autre)
        
    if not route_orientee.index.is_unique:
        print("Not unique !")
        route_orientee = route_orientee.reset_index()
        route_orientee['key'] = route_orientee.groupby(['u', 'v']).cumcount(ascending = True)
        
        print(route_orientee[["u", "v",'key']][route_orientee["key"]!=0 ])
        print(f" Doublons restants : {route [['u', 'v', 'key']] [route.duplicated(subset = ['u','v', 'key'])]} ")

        route_orientee = route_orientee.set_index(['u', 'v', 'key'])
    
    gdf_nodes = table_noeuds(route)
    reseau_routier = ox.graph_from_gdfs(gdf_nodes, route_orientee, graph_attrs={"crs": route.crs})
    print(f"Composantes faiblement connexes : {nx.number_weakly_connected_components(reseau_routier)}")
    print(f"Est fortement connecté : {nx.is_strongly_connected(reseau_routier)}")
    print(f"Est faiblement connecté : {nx.is_weakly_connected(reseau_routier)}")
    print(f"Est semi-connecté : {nx.is_semiconnected(reseau_routier)}")
    return reseau_routier
#%%Nettoyage du graphe

def doublon_noeuds(graphe, tolerance = 1.0):
    nodes = dict(graphe.nodes(data=True))
    coords = np.array([(d['x'], d['y']) for d in nodes.values()])
    node_ids = list(nodes.keys())

    # Chercher les paires de nœuds très proches (< 1 mètre en EPSG:2154)
    tree = KDTree(coords)
    paires = tree.query_pairs(r=1.0) 

    print(f"Paires de nœuds quasi-doublons : {len(paires)}")

    # Visualiser quelques exemples
    for i, j in list(paires)[:5]:
        n1, n2 = node_ids[i], node_ids[j]
        d1, d2 = nodes[n1], nodes[n2]
        dist = np.sqrt((d1['x']-d2['x'])**2 + (d1['y']-d2['y'])**2)
        print(f"  {n1} ↔ {n2} | distance : {dist:.4f}m")
    if len(paires)>0 :
        graphe_fusionne = snap_nodes(graphe, tolerance)
        return graphe_fusionne
    return graphe
    
def snap_nodes(G, tolerance=1.0):
    """Fusionne les nœuds situés à moins de `tolerance` mètres."""
    
    nodes = dict(G.nodes(data=True))
    node_ids = list(nodes.keys())
    
    #Permet de ne pas toucher aux cul-de-sacs
    #A voir si efficace
    noeuds_a_fusionner = [n for n in node_ids if (G.degree(n) > 1)]
    if not noeuds_a_fusionner:
        return G
    
    coords = np.array([(d['x'], d['y']) for d in nodes.values()])
    
    # Trouver les groupes de nœuds proches
    tree = KDTree(coords)
    paires = tree.query_pairs(r=tolerance)
    
    # Construire les groupes via Union-Find
    parent = {n: n for n in node_ids}
    
    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    
    def union(a, b):
        parent[find(a)] = find(b)
    
    for i, j in paires:
        union(node_ids[i], node_ids[j])
    
    # Mapping de l'ancien nœud vers le représentant du groupe
    mapping = {n: find(n) for n in node_ids}
    #mapping = {node_ids[i]: node_ids[find(i)] for i in range(len(node_ids))}
    # Relabelliser le graphe
    G_snapped = nx.MultiDiGraph()
    G_snapped.graph.update(G.graph)
    
    # Ajouter les noeuds représentants uniquement
    noeuds_representants = set(mapping.values())
    for n in noeuds_representants:
        G_snapped.add_node(n, **G.nodes[n])
    
    # Ajouter les arêtes en remappant u et v mais en conservant tous les attributs
    for u, v,k, data in G.edges(keys = True,data=True):
        new_u = mapping[u]
        new_v = mapping[v]
        
        # Ignorer les boucles créées par la fusion
        if new_u == new_v:
            continue
        edge_data = dict(data)
        
        #Maj géométrie si les noeuds ont été remappés
        if "geometry" in edge_data and (new_u != u or new_v != v):
            geom = edge_data["geometry"]
            coords_geom = [(c[0], c[1]) for c in geom.coords]
            #print([len(c) for c in coords_geom])  #Faut avoir que des 2 (nb de coords) sinon c'est pas bon
            # Remplacer le premier point par les coords du nouveau noeud source
            coords_geom[0] = (G_snapped.nodes[new_u]['x'], G_snapped.nodes[new_u]['y'])
            # Remplacer le dernier point par les coords du nouveau noeud destination
            coords_geom[-1] = (G_snapped.nodes[new_v]['x'], G_snapped.nodes[new_v]['y'])
            
            edge_data["geometry"] = LineString(coords_geom)
        
        G_snapped.add_edge(new_u, new_v, **edge_data)
        #Supprimer les boucles créées par la fusion
        G_snapped.remove_edges_from(nx.selfloop_edges(G_snapped))
    
    print("--- Fin de la fusion ---")   
    print(f"Nœuds avant : {G.number_of_nodes()} | après : {G_snapped.number_of_nodes()}")
    print(f"Nœuds fusionnés : {G.number_of_nodes() - G_snapped.number_of_nodes()}")

    return G_snapped



#%%Fonctions de temps de trajet

def ponderer_distance_pieton(graphe, colonne_vitesse):
   
    for u, v, data in graphe.edges(data=True):
        nature_a_eviter = ["Bretelle", "Type autoroutier"]
        classement =["Départementale", "Nationale"]
        geom = data.get("geometry")
        vitesse_numerique = 4 #temps de marche moyen
        print(f"Longueur initiale : {data.get('length')}")
        
        if data.get("length") == None:
            length = geom.length
            data["length"] = length
        else:
            length = data.get("length")
        print(length)
        
        
        if "grade" in data:
            # z_depart = graphe.nodes[u]['elevation']
            # z_arrivee = graphe.nodes[v]['elevation']
            pente = data.get("grade",0)
            vitesse_numerique = 6 * np.exp(-3.5*abs(pente+0.05)) #Fonction de Tobler
        
        data["travel_time"] = length/(vitesse_numerique /3.6) #en secondes

        #On exclut les autoroutes et autres routes
        #non empruntables à pied
        if data.get("nature") in nature_a_eviter or data.get(colonne_vitesse,0) > 60 or (data.get("cpx_classement_administratif") in classement and data.get("urbain") == "false" ):
            vitesse_numerique = 0
            data["travel_time"] = float("inf")
        data["speed_kph"] = vitesse_numerique
        data["mode"] = 'walk'
        
        
def ponderer_distance_velo(graphe):
   
    for u, v, data in graphe.edges(data=True):
        geom = data.get("geometry")
        vitesse_numerique = 20
        #A diminuer en ville ?
        #Corréler avec la pente
        if data.get("length") == None:
            length = geom.length
            data["length"] = length
        else:
            length = data.get("length")
        
        if "grade" in data:
            # z_depart = graphe.nodes[u]['elevation']
            # z_arrivee = graphe.nodes[v]['elevation']
            pente = data.get("grade",0) 
            
            vitesse_numerique = 18 * np.exp(-3.5*abs(pente+0.05))
           
        print(data.get("length"))
        
        print(length)
        data["travel_time"] = length/(vitesse_numerique /3.6)
        data["speed_kph"] = vitesse_numerique
        data["mode"] = 'bike'


def ponderer_distance_voiture(graphe,colonne_vitesse):
    
    nature = ("Chemin", "Sentier", "Escalier")
    restriction = ("Piste cyclable", "Voie verte")
    for u, v, data in graphe.edges(data=True):
        vitesse = data.get(colonne_vitesse, 50)#On met une vitesse de 50km/h par défaut
        if isinstance(vitesse, list):
            vitesse = vitesse[0]
        
        #Nettoyage et conversion
        if isinstance(vitesse, str):
            # On extrait uniquement les chiffres
            extraction = re.findall(r'\d+', vitesse)
            if extraction:
                vitesse = float(extraction[0])
            else:
                    vitesse = 50.0  #Valeur de secours
        
        if data.get("length") == None:
            length = data.get("geometry").length
            data["length"] = length
        else:
            length = data.get("length")
        vitesse_numerique = float(vitesse) if vitesse  else 50.0
        
        
        if vitesse_numerique == 0 or data.get("nature") in nature or data.get("nature_de_la_restriction") in restriction:
            #On ne peut pas prendre ce tronçon en voiture
            data["travel_time"] = float("inf")
            
        else:
            data["travel_time"] = length/(vitesse_numerique /3.6)
        
        data["speed_kph"] = vitesse_numerique
        data["mode"] = 'car'
def ponderer_distance_train(graphe):
   
    for u, v, data in graphe.edges(data=True):
        geom = data.get("geometry")
        vitesse = data.get("vitesse_moyenne_vl", 100)
        if isinstance(vitesse, str):
            # On extrait uniquement les chiffres
            extraction = re.findall(r'\d+', vitesse)
            if extraction:
                vitesse_numerique = float(extraction[0])
            else:
                    vitesse_numerique = 100.0
        vitesse_numerique = float(vitesse) if vitesse  else 100.0
        if data.get("length") == None:
            length = geom.length
            data["length"] = length
        else:
            length = data.get("length")
        
        
            
           
        print(data.get("length"))
        
        print(length)
        data["travel_time"] = length/(vitesse_numerique /3.6)
        data["speed_kph"] = vitesse_numerique
        data["mode"] = 'train'

#%%Main
if __name__ == "__main__":
    print("Fonction graphe!")
    