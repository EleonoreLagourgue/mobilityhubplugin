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
import panda as pd
def nearest_node(G, lat, lon):
    return ox.nearest_nodes(G, lon, lat)

def lat_lon(layer):
    nom_champs=[]
    layer.startEditing()
    for i in layer.fields():
        nom_champs.append(i.name())
    if ("lon" not in nom_champs):
        layer.dataProvider().addAttributes([QgsField("lon",QVariant.String)])
    if ("lat" not in nom_champs):
        layer.dataProvider().addAttributes([QgsField("lat",QVariant.String)])
  
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
    HUBS = "HUBS"
    DESTINATION = "DESTINATION"
    MODE = "MODE"
    WEIGHT = "WEIGHT"
   
   
    
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
        self.addParameter(QgsProcessingParameterFeatureSource(self.RESEAU, "Lignes du réseau (lignes)"))

        self.addParameter(QgsProcessingParameterFeatureSource(self.POP, 
                                                              "Nœuds de population (points)",
                                                              [QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.HUBS,
                                                              "Hubs candidats (points)",
                                                              [QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.DESTINATION,
                                                              "Destinations (si différent de nœuds de population) ",
                                                              [QgsProcessing.SourceType.TypeVectorPoint],
                                                              optional = True))
        
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
        self.addParameter(QgsProcessingParameterField(self.WEIGHT, "Colonne poids", parentLayerParameterName=self.INPUT))

    def processAlgorithm(self, parameters, context, feedback):
        pop_layer = self.parameterAsVectorLayer(parameters, self.POP, context)#QgsProcessingFeatureSource
        hubs_layer = self.parameterAsVectorLayer(parameters, self.HUBS, context)#QgsProcessingFeatureSource
        dest_layer = self.parameterAsVectorLayer(parameters, self.DESTINATION, context)#QgsProcessingFeatureSource
        
        lignes_layer = self.parameterAsVectorLayer(parameters, self.LIGNES, context)#QgsProcessingFeatureSource
        nodes_layer = self.parameterAsVectorLayer(parameters, self.NODES, context)#QgsProcessingFeatureSource

        feedback.pushInfo("Construction de la matrice de temps ...")
        nom_champs=[]
        
        hubs_layer= lat_lon(hubs_layer)
 
        pop_layer= lat_lon(pop_layer)
        
        pop_layer =processing.run("native:mergevectorlayers", {'LAYERS': [hubs_layer, pop_layer],
                                                    "OUTPUT": "memory:"})["OUTPUT"]

        
        nom = self.parameterAsString(parameters, self.MODE, context)
        nodes = qgis_layer_to_gdf(nodes_layer)
        edges = qgis_layer_to_gdf(lignes_layer)
        G = ox.graph_from_gdfs(nodes, edges)
        origin = qgis_layer_to_gdf(pop_layer)
        
        if dest_layer is None:
            origin[f"node_{nom}"] = origin.apply(lambda r: nearest_node(G,r["lat"], r["lon"]), axis=1)
            gdf = origin[f"node_{nom}"]
     
        else:
            
            dest_layer= lat_lon(dest_layer)

            dest = qgis_layer_to_gdf(dest_layer)
            origin[f"node_{nom}"] = origin.apply(lambda r: nearest_node(G,r["lat"], r["lon"]), axis=1)
            dest[f"node_{nom}"] = dest.apply(lambda r: nearest_node(G,r["lat"], r["lon"]), axis=1)
            gdf = pd.concat([origin[f"node_{nom}"],dest[f"node_{nom}"]])
            
        print(gdf)
        dict_matrix ={}
        index = []
        for i, src in gdf.items():
            #Dijkstra depuis src vers tous les autres noeuds
            lengths = nx.single_source_dijkstra_path_length(
                G, src, weight=weight)
            for j, dst in gdf.items():
                if dst in lengths:
                    dict_matrix[str(j)] = lengths[dst]/60 #on passe des secondes aux minutes
                else:
                    dict_matrix[j] = np.inf
                index.append(str(i))
        matrix = pd.DataFrame(dict_matrix, index = index)
        
        #renvoie un csv/txt
        if dest.empty:
            return matrix, origin
        else:
            return matrix, origin,dest