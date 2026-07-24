# -*- coding: utf-8 -*-
"""
Created on Thu Jul 16 14:46:46 2026

@author: eleonore.lagourgue
"""

from qgis.PyQt.QtCore import QCoreApplication,QVariant
from qgis.core import *
from qgis.utils import *
# from qgis.core import (QgsProcessing,
#                        QgsFeatureSink,
#                        QgsProcessingAlgorithm,
#                        QgsProcessingParameterFeatureSource,
#                        QgsProcessingParameterFeatureSink,
#                        QgsProcessingParameterNumber,
#                        QgsProcessingParameterBoolean,
#                        QgsProcessingParameterString,
#                        QgsProcessingParameterExtent,
#                        QgsProcessingParameterField,
#                        QgsProcessingParameterExpression,
#                        QgsProcessingParameterFileDestination,
#                        QgsSpatialIndex,
#                        QgsGeometry,
#                        QgsFeature,
#                        QgsField,
#                        QgsFields,
#                        QgsCoordinateTransform,
#                        QgsCoordinateReferenceSystem
#                        )

from qgis import processing

from mobilityhubplugin.conversions import (qgis_layer_to_gdf, 
                         gdf_geom_to_qgs_wkbtype,
                         gdf_to_qgsfields,
                         write_gdf_to_sink)
import osmnx as ox
import networkx as nx
import pandas as pd
import numpy as np

def nearest_node(G, lat, lon):
    return ox.nearest_nodes(G, lon, lat)

def add_nearest_node(layer, G, field_name, colonne_id,feedback=None):
    nom_champs = [f.name() for f in layer.fields()]

    if not layer.isEditable():
        layer.startEditing()

    
    if (field_name not in nom_champs):
        layer.dataProvider().addAttributes([QgsField(field_name,QVariant.Int)])
    
    layer.updateFields()
    idx = layer.fields().indexFromName(field_name)
    
    feats = list(layer.getFeatures())
    if not feats:
        layer.commitChanges()
        return {}

        
        
    ids = []
    xs = []  # longitude
    ys = []  # latitude
    seen_ids = set()
    for feat in feats:
        code = feat[colonne_id]
        if code in seen_ids and feedback:
            feedback.pushWarning(
                f"Identifiant '{code}' dupliqué dans la colonne '{colonne_id}' "
                f"de la couche '{layer.name()}' : les doublons s'écraseront."
            )
        seen_ids.add(code)
        pt = feat.geometry().asPoint()
        ids.append(code)
        xs.append(pt.x())  # X = longitude
        ys.append(pt.y())  # Y = latitude
 
    # Un seul appel vectorisé : X = longitudes, Y = latitudes (ordre correct)
    nearest = ox.nearest_nodes(G, X=xs, Y=ys)
    if np.isscalar(nearest):
        nearest = [nearest]
 
    values = {}
    for feat, code, node in zip(feats, ids, nearest):
        values[code] = node
        layer.changeAttributeValue(feat.id(), idx, int(node))
 
    ok = layer.commitChanges()
    if not ok and feedback:
        feedback.pushWarning(
            f"Impossible d'enregistrer les modifications sur la couche '{layer.name()}'."
        )
    return values



def lat_lon(layer):
    nom_champs=[]
    layer.startEditing()
    for i in layer.fields():
        nom_champs.append(i.name())
    if ("lon" not in nom_champs):
        layer.dataProvider().addAttributes([QgsField("lon",QVariant.Int)])
    if ("lat" not in nom_champs):
        layer.dataProvider().addAttributes([QgsField("lat",QVariant.Int)])
  
    layer.updateFields()
    layer.commitChanges()
    return layer

class MatriceTemps(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    NODES = "NODES"
    RESEAU = "RESEAU"
    POP = "POP"
    IDPOP = "IDPOP"
    HUBS = "HUBS"
    IDHUB = "IDHUB"
    DESTINATION = "DESTINATION"
    IDDEST ="IDDEST"
    MODE = "MODE"
    WEIGHT = "WEIGHT"
    MATRIX = "MATRIX"
   
    
    def createInstance(self):
        return MatriceTemps()

    def name(self):
        return "matrice_temps"

    def displayName(self):
        return "Crée une matrice de temps de trajet"

    def group(self):
        return "Analyse réseau"

    def groupId(self):
        return "analyse_reseau"
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.NODES, 
                                                              "Nœuds du réseau (points)",
                                                              [QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.RESEAU, 
                                                              "Lignes du réseau (lignes)",
                                                              [QgsProcessing.SourceType.TypeVectorLine]))

        self.addParameter(QgsProcessingParameterField(self.WEIGHT, 
                                                      "Colonne poids",
                                                      parentLayerParameterName=self.RESEAU))
        
        self.addParameter(QgsProcessingParameterFeatureSource(self.POP, 
                                                              "Nœuds de population (points)",
                                                              [QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(self.IDPOP, 
                                                      "Colonne id pour la couche de population",
                                                      parentLayerParameterName=self.POP))
        self.addParameter(QgsProcessingParameterFeatureSource(self.HUBS,
                                                              "Hubs candidats (points)",
                                                              [QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(self.IDHUB, 
                                                      "Colonne id pour la couche des hubs",
                                                      parentLayerParameterName=self.HUBS))
        
        self.addParameter(
        QgsProcessingParameterEnum(
        self.MODE,
        'Choisir un mode de déplacement',
        options=['Voiture', 'Piéton', 'Vélo','Train'],
        allowMultiple=False,
        defaultValue=0,   # index par défaut (0 = premier élément)
        optional=False    # <-- rend le paramètre obligatoire
            )
        )
        
        
        #----------Paramètres optionnels#----------
        self.addParameter(QgsProcessingParameterFeatureSource(self.DESTINATION,
                                                              "Destinations (si différent de nœuds de population) ",
                                                              [QgsProcessing.SourceType.TypeVectorPoint],
                                                              optional = True))
                                                      
        self.addParameter(QgsProcessingParameterField(self.IDDEST, 
                                              "Colonne id pour la couche de destination",
                                              parentLayerParameterName=self.DESTINATION,
                                              optional = True))
        
        
        
        
        self.addParameter(QgsProcessingParameterFileDestination(self.MATRIX, 
                                                                "Fichier d'emplacement de la matrice de temps",
                                                                fileFilter='*.csv',
                                                                defaultValue='*.csv'))

    def processAlgorithm(self, parameters, context, feedback):
        pop_layer = self.parameterAsVectorLayer(parameters, self.POP, context)#QgsProcessingFeatureSource
        hubs_layer = self.parameterAsVectorLayer(parameters, self.HUBS, context)#QgsProcessingFeatureSource
        dest_layer = self.parameterAsVectorLayer(parameters, self.DESTINATION, context)#QgsProcessingFeatureSource
        
        lignes_layer = self.parameterAsVectorLayer(parameters, self.RESEAU, context)#QgsProcessingFeatureSource
        nodes_layer = self.parameterAsVectorLayer(parameters, self.NODES, context)#QgsProcessingFeatureSource
        weight = self.parameterAsString(parameters, self.WEIGHT, context)
        id_pop = self.parameterAsString(parameters, self.IDPOP, context)
        id_hub = self.parameterAsString(parameters, self.IDHUB, context)

        id_mode = self.parameterAsInt(parameters, self.MODE, context)
        fichier_sortie=self.parameterAsFileOutput(parameters, self.MATRIX, context)

        feedback.pushInfo("Construction de la matrice de temps ...")
        modes = ['Voiture', 'Piéton', 'Vélo','Train']
        
        nodes = qgis_layer_to_gdf(nodes_layer)
        edges = qgis_layer_to_gdf(lignes_layer)
        nodes = nodes.set_index("osmid")
        edges = edges.set_index(["u", "v", "key"])
        G = ox.graph_from_gdfs(nodes, edges)
        
        nom = modes[id_mode]
        node_field = f"node_{nom}"
        nodes_hubs = add_nearest_node(hubs_layer, G, node_field, id_hub, feedback=feedback)
        nodes_pop  = add_nearest_node(pop_layer, G, node_field, id_pop, feedback=feedback) #renvoie un dict
        
        all_nodes = {} #dictionnaire
        for fid, node in nodes_hubs.items():
            all_nodes[f"hub_{fid}"] = node
        for fid, node in nodes_pop.items():
            all_nodes[f"pop_{fid}"] = node
        
        #Si destination différente de pop (pour les POIs)
        if dest_layer is not None:
            id_dest = self.parameterAsString(parameters, self.IDDEST, context)
            
            nodes_dest = add_nearest_node(dest_layer, G, node_field, id_dest, feedback=feedback)
            for fid, node in nodes_dest.items():
                all_nodes[f"dest_{fid}"] = node
        
        feedback.pushInfo("Fin formatage  ...")

        
        dict_matrix ={}
        index = []
        for i in all_nodes:
            #Dijkstra depuis src vers tous les autres noeuds
            src = all_nodes[i]
            lengths = nx.single_source_dijkstra_path_length(
                G, src, weight=weight)
            row = {}
            for j in all_nodes:
                dest = all_nodes[j]

                if dest in lengths:
                    row[str(j)] = lengths[dest]/60 #on passe des secondes aux minutes
                else:
                    row[str(j)] = np.inf
            feedback.pushInfo(f"ligne : {row}")
            dict_matrix[str(i)] = row 
        matrix = pd.DataFrame(dict_matrix, index = index)
        
        #renvoie un csv/txt
        feedback.pushInfo(f"matrice : {matrix}")
        matrix.to_csv(fichier_sortie)
        return {self.MATRIX: fichier_sortie}
            #return origin,dest