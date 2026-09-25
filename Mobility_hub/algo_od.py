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
    QgsProcessingParameterString,
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
import csv
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
        return 'Formatage préliminaire'

    def groupId(self):
        return 'formatage'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.OD_MATRIX, 
                                                     "Matrice OD (fichier)",
                                                     behavior=QgsProcessingParameterFile.File))
        self.addParameter(QgsProcessingParameterString(self.ORIGINE, 
                                                      "Colonne origine"
                                                     ))
        self.addParameter(QgsProcessingParameterString(self.DESTINATION, 
                                                      "Colonne destination"
                                                      ))
        self.addParameter(QgsProcessingParameterString(self.COMPTEUR, 
                                                      "Colonne renseignant le poids de l'individu (ex: avec les données Mobpro colonne IPONDI)"
                                                     ))
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

        od_matrix = pd.read_csv(nodes_file,  
                                sep=None,dtype={origine: str, dest: str},
                                engine='python')
        feedback.pushInfo(f"Colonnes lues : {od_matrix.columns.tolist()}")
        feedback.pushInfo(f"Type origine lu : {od_matrix[origine][:5]}")
        feedback.pushInfo(f"Shape : {od_matrix.shape}")
                
        valeurs_reelles = set(od_matrix.columns)

        for label, val in [("Origine", origine),
                            ("Destination", dest),
                            ("Volume", cpt)]:
            if val not in valeurs_reelles:
                feedback.reportError(
                    f"La valeur '{val}' ({label}) n'existe pas dans la  "
                    f"'matrice OD'. Valeurs disponibles : {sorted(valeurs_reelles)}",
                    fatalError=True
                )
                return {}
        flux =(od_matrix
                .groupby([origine, dest])[cpt]
                .sum()
                .reset_index()
                .rename(columns={origine: "origine_id",
                                 dest:    "destination_id",
                                 cpt:  "volume"}))
        flux["origine_id"] = flux["origine_id"].astype(str)
        flux["destination_id"] = flux["destination_id"].astype(str)
        feedback.pushInfo(f"Type origine lu : {flux['origine_id'][:5]}")

        flux.to_csv(output_file, quoting=csv.QUOTE_NONNUMERIC)
        feedback.pushInfo("Fait !")
        
        return {self.OD_MATRIX:self.OD_MATRIX}