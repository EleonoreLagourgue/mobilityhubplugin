# -*- coding: utf-8 -*-
"""
Created on Thu Jul 23 15:44:23 2026

@author: eleonore.lagourgue
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from mobilityhubplugin.conversions import build_workplace_problem_data

import pandas as pd
class FormateODmatrix(QgsProcessingAlgorithm):
    
    OD_MATRIX = "OD_MATRIX"
    ORIGINE = "ORIGINE"
    DESTINATION = "DESTINATION"
    COMPTEUR = "COMPTEUR"
    OUTPUT = "OUTPUT"
    def createInstance(self):
        return FormateODmatrix()

    def name(self):
        return "formate_od_matrix"

    def displayName(self):
        return "Formater les données Origine-Destination"

    def group(self):
        return 'Traitements annexes'

    def groupId(self):
        return 'traitements_annexes'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.OD_MATRIX, 
                                                     "Matrice OD (fichier)",
                                                     behavior=QgsProcessingParameterFile.File))
        self.addParameter(QgsProcessingParameterField(self.ORIGINE, 
                                                      "Colonne origine",
                                                      parentLayerParameterName=self.OD_MATRIX))
        self.addParameter(QgsProcessingParameterField(self.DESTINATION, 
                                                      "Colonne destination",
                                                      parentLayerParameterName=self.OD_MATRIX))
        self.addParameter(QgsProcessingParameterField(self.COMPTEUR, 
                                                      "Colonne renseignant le poids de l'individu (ex: avec les données Mobpro colonne IPONDI)",
                                                      parentLayerParameterName=self.OD_MATRIX))
        self.addParameter(
            QgsProcessingParameterFileDestination(self.OUTPUT, "Fichier de sortie",
                                       fileFilter='*.csv',
                                       defaultValue='*.csv')
        )
       
    def processAlgorithm(self, parameters, context, feedback):
        nodes_file = self.parameterAsFile(parameters, self.OD_MATRIX, context)
        origine = self.parameterAsString(parameters, self.ORIGINE, context)
        dest = self.parameterAsString(parameters, self.DESTINATION, context)
        cpt = self.parameterAsString(parameters, self.COMPTEUR, context)
        output_file = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        od_matrix = pd.read_csv(nodes_file)
        feedback.pushInfo(od_matrix)
        feedback.pushInfo(od_matrix[origine])


        flux =(od_matrix
                .groupby([origine, dest])[cpt]
                .sum()
                .reset_index()
                .rename(columns={origine: "origine_id",
                                 dest:    "destination_id",
                                 cpt:  "volume"}))
        flux.to_csv(output_file)
        feedback.pushInfo("Fait !")
        
        return {self.OD_MATRIX:self.OD_MATRIX}