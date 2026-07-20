# -*- coding: utf-8 -*-
"""
Created on Thu Jul 16 14:46:46 2026

@author: eleonore.lagourgue
"""

from qgis.PyQt.QtCore import QCoreApplication,QVariant
from qgis.core import *
from qgis.utils import *
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterString,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterField,
                       QgsProcessingParameterExpression,
                       QgsProcessingParameterFileDestination,
                       QgsSpatialIndex,
                       QgsGeometry,
                       QgsFeature,
                       QgsField,
                       QgsFields,
                       QgsCoordinateTransform,
                       QgsCoordinateReferenceSystem
                       )

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
        self.addParameter(QgsProcessingParameterFeatureSource(self.NODES, "Nœuds du réseau (points)"))
        self.addParameter(QgsProcessingParameterFeatureSource(self.RESEAU, "Lignes du réseau (lignes)"))

        self.addParameter(QgsProcessingParameterFeatureSource(self.POP, "Nœuds de population (points)"))
        self.addParameter(QgsProcessingParameterFeatureSource(self.HUBS, "Hubs candidats (points)"))
        self.addParameter(QgsProcessingParameterFeatureSource(self.DESTINATION, "Destinations (si différent de nœuds de population) "))

    def processAlgorithm(self, parameters, context, feedback):
        nodes_src = self.parameterAsSource(parameters, self.NODES, context)#QgsProcessingFeatureSource
        hubs_src = self.parameterAsSource(parameters, self.HUBS, context)#QgsProcessingFeatureSource
        dest_src = self.parameterAsSource(parameters, self.DESTINATION, context)#QgsProcessingFeatureSource
        
        feedback.pushInfo("Construction des itinéraires potentiels (routage + élimination des dominés)...")
