# -*- coding: utf-8 -*-
"""
Created on Thu Jul 16 14:25:15 2026

@author: eleonore.lagourgue
"""

# build_graph_algorithm.py
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingOutputString,
    QgsProcessingOutputLayerDefinition,
    QgsProcessingParameterString,
    QgsProcessingParameterFeatureSink,
    QgsFeature, QgsGeometry, QgsFields, QgsField,
    QgsWkbTypes, QgsCoordinateReferenceSystem,
)
from qgis.analysis import QgsVectorLayerDirector
from qgis.PyQt.QtCore import QVariant, QCoreApplication

from .fonction_graphe import (crea_graphe, doublon_noeuds, 
                              ponderer_distance_voiture,
                              ponderer_distance_velo,
                              ponderer_distance_pieton,
                              ponderer_distance_train,
                              SOURCE_PROFILES,
                              NO_FACILITY_VALUES
)
from mobilityhubplugin.conversions import (qgis_layer_to_gdf, 
                         gdf_geom_to_qgs_wkbtype,
                         gdf_to_qgsfields,
                         write_gdf_to_sink)
from collections import OrderedDict


import osmnx as ox
import networkx as nx




class BuildGraphAlgorithm(QgsProcessingAlgorithm):

    INPUT = "INPUT"
    DIRECTION_FIELD = 'DIRECTION_FIELD'
    VALUE_FORWARD = 'VALUE_FORWARD'
    VALUE_BACKWARD = 'VALUE_BACKWARD'
    VALUE_BOTH = 'VALUE_BOTH'
    DEFAULT_DIRECTION = 'DEFAULT_DIRECTION'
    SPEED_FIELD = 'SPEED_FIELD'
    DEFAULT_SPEED = 'DEFAULT_SPEED'
    MODE = "MODE"
    TOLERANCE = 'TOLERANCE'
    COLAME ="COLAME"
    SOURCE = 'SOURCE'
    VALEURS_PERSONNALISEES = 'VALEURS_PERSONNALISEES'
    LIGNES = 'LIGNES'
    NOEUDS = "NOEUDS"
    
    SOURCE_OPTIONS = list(SOURCE_PROFILES.keys()) + ['Personnalisé']

    def __init__(self):
        super().__init__()
        
    def initAlgorithm(self, config=None):
        self.DIRECTIONS = OrderedDict([
            ('Forward direction', QgsVectorLayerDirector.DirectionForward),
            ('Backward direction', QgsVectorLayerDirector.DirectionBackward),
            ('Both directions', QgsVectorLayerDirector.DirectionBoth)])
        
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, self.tr("Réseau")))
        self.addParameter(QgsProcessingParameterField(self.DIRECTION_FIELD, 
                                                      self.tr("Colonne direction"),
                                                      parentLayerParameterName=self.INPUT,
                                                      optional= True))
        self.addParameter(QgsProcessingParameterString(self.VALUE_FORWARD, 
                                                       self.tr("Sens direct (à remplir si la colonne de direction est renseignée)"),
                                                       optional=True,
                                                       defaultValue=None))
        self.addParameter(QgsProcessingParameterString(self.VALUE_BACKWARD, 
                                                       self.tr("Sens inverse (à remplir si la colonne de direction est renseignée)"),
                                                       optional = True,
                                                       defaultValue=None))
        self.addParameter(QgsProcessingParameterString(self.VALUE_BOTH, 
                                                       self.tr("Double sens (à remplir si la colonne de direction est renseignée)"),
                                                       optional=True,
                                                       defaultValue=None))
        self.addParameter(QgsProcessingParameterEnum(self.DEFAULT_DIRECTION,
                                                 self.tr("Direction par défaut"),
                                                 list(self.DIRECTIONS.keys()),
                                                 optional = True,
                                                 defaultValue=None))

        self.addParameter(QgsProcessingParameterField(self.SPEED_FIELD, 
                                                      self.tr("Colonne vitesse"), 
                                                      parentLayerParameterName=self.INPUT,
                                                      optional=True))
        self.addParameter(QgsProcessingParameterString(self.DEFAULT_SPEED, 
                                                       self.tr("Vitesse par défaut"), 
                                                       defaultValue=50))
        
        self.addParameter(QgsProcessingParameterField(self.COLAME, 
                                                      self.tr("Colonne(s) aménagements"),
                                                      parentLayerParameterName=self.INPUT,
                                                      optional= False,
                                                      allowMultiple = True))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOURCE,
                self.tr("Source des données (détermine les valeurs valides par colonne)"),
                options=self.SOURCE_OPTIONS,
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.VALEURS_PERSONNALISEES,
                self.tr(
                    "Valeurs indiquant un aménagement (mode Personnalisé uniquement, "
                    "séparées par des virgules, ex: Piste cyclable,Bande cyclable)"
                ),
                optional=True
            )
        )
        
        self.addParameter(QgsProcessingParameterNumber(self.TOLERANCE, self.tr("Tolérance topologique (en mètres)"), defaultValue=0.0))

        self.addParameter(
        QgsProcessingParameterEnum(
        self.MODE,
        self.tr('Choisir un mode de déplacement'),
        options=['Voiture', 'Piéton', 'Vélo','Train'],
        allowMultiple=False,
        defaultValue=0,   # index par défaut (0 = premier élément)
        optional=False    
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink(self.LIGNES, self.tr("Couche linéaire du graphe")))
        self.addParameter(QgsProcessingParameterFeatureSink(self.NOEUDS, self.tr("Couche des noeuds du graphe")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        tolerance = self.parameterAsDouble(parameters, self.TOLERANCE, context)
        colonne_direction = self.parameterAsString(parameters, self.DIRECTION_FIELD, context)
        value_forward = self.parameterAsString(parameters, self.VALUE_FORWARD, context)
        value_backward = self.parameterAsString(parameters, self.VALUE_BACKWARD, context)
        value_both = self.parameterAsString(parameters, self.VALUE_BOTH, context)
        default_direction = self.parameterAsString(parameters, self.DEFAULT_DIRECTION, context)
        
        mode = self.parameterAsInt(parameters, self.MODE, context)
        colonne_vitesse =  self.parameterAsString(parameters, self.SPEED_FIELD, context)
        
        col_ame = self.parameterAsStrings(parameters, self.COLAME, context)
        source_idx = self.parameterAsEnum(parameters, self.SOURCE, context)
        source_name = self.SOURCE_OPTIONS[source_idx]
        valeurs_perso_str = self.parameterAsString(parameters, self.VALEURS_PERSONNALISEES, context)
        
        if colonne_direction != "":
            feedback.pushInfo("La colonne est renseignée")
            feedback.pushInfo(f'{colonne_direction}')


            valeurs_reelles = set(layer.uniqueValues(layer.fields().indexOf(colonne_direction)))
    
            for label, val in [("sens direct", value_forward),
                                ("sens inverse", value_backward),
                                ("double sens", value_both)]:
                if val not in valeurs_reelles:
                    feedback.reportError(
                        f"La valeur '{val}' ({label}) n'existe pas dans la colonne "
                        f"'{colonne_direction}'. Valeurs disponibles : {sorted(valeurs_reelles)}",
                        fatalError=True
                    )
                    return {}
        else:
            colonne_direction =None
            value_forward = None
            value_backward = None
            value_both = None
            default_direction = None
            
        # Vérification des valeurs d'aménagements cyclables
        if source_name == 'Personnalisé':
            profile = None
            custom_values = [v.strip() for v in valeurs_perso_str.split(',') if v.strip()] or None
            if not custom_values:
                feedback.pushWarning(
                    "Mode Personnalisé sans valeurs renseignées : repli sur "
                    "IS NOT NULL (hors valeurs 'vides' usuelles) pour toutes les colonnes."
                )
        else:
            profile = SOURCE_PROFILES.get(source_name, {})
            col_ame = []
            for col in profile.keys():
                idx = layer.fields().indexOf(col)
                if idx == -1:
                    feedback.pushInfo(f"Attention : attribut {col} pas présent dans la couche")
                else:
                    col_ame.append(col)
                pass
            custom_values = None

        feedback.pushInfo(f"Colonnes sélectionnées : {col_ame} (source : {source_name})")
        
        gdf_route = qgis_layer_to_gdf(layer)
        feedback.pushInfo(f"mode : {mode}")

        feedback.pushInfo("Construction du graphe")

        # Choix du mode de transport
        if mode ==0:
            graph = crea_graphe(gdf_route, colonne_direction, value_forward, value_backward, value_both, mode ="drive")
            feedback.pushInfo("Vérification des doublons")
            graph_snapped = doublon_noeuds(graph, tolerance=tolerance)
            print(f"Nœuds avant : {graph.number_of_nodes()} | après : {graph_snapped.number_of_nodes()}")
            feedback.pushInfo("Calcul vitesse")
            ponderer_distance_voiture(graph_snapped, colonne_vitesse,col_ame, profile=profile, custom_values=custom_values)
        
        elif mode == 1:
            graph = crea_graphe(gdf_route, colonne_direction, value_forward, value_backward, value_both, mode ="walk")
            feedback.pushInfo("Vérification des doublons")
            graph_snapped = doublon_noeuds(graph, tolerance=tolerance)
            feedback.pushInfo("Calcul vitesse")
            ponderer_distance_pieton(graph_snapped, colonne_vitesse,col_ame,profile=profile, custom_values=custom_values)
        
        elif mode == 2:
            graph = crea_graphe(gdf_route, colonne_direction, value_forward, value_backward, value_both, mode ="bike")
            feedback.pushInfo("Vérification des doublons")
            graph_snapped = doublon_noeuds(graph, tolerance=tolerance)
            feedback.pushInfo("Calcul vitesse")
            ponderer_distance_velo(graph_snapped,col_ame,profile=profile, custom_values=custom_values)
        
        elif mode == 3:
            graph = crea_graphe(gdf_route, colonne_direction, value_forward, value_backward, value_both, mode ="walk")
            feedback.pushInfo("Vérification des doublons")
            graph_snapped = doublon_noeuds(graph, tolerance=tolerance)
            print(f"Composantes faiblement connexes : {nx.number_weakly_connected_components(graph_snapped)}")

            graph_snapped = ox.truncate.largest_component(graph_snapped)

            feedback.pushInfo("Calcul vitesse")
            ponderer_distance_train(graph_snapped)
            
            
        feedback.pushInfo(f"Graphe construit : {graph_snapped.number_of_edges()} sommets, {graph_snapped.number_of_nodes()} arêtes")
        nodes, lines = ox.graph_to_gdfs(graph_snapped)
        nodes = nodes.reset_index()
        lines = lines.reset_index()

        crs = layer.crs()  # on réutilise le CRS de la couche d'entrée

        # --- Sink lignes ---
        lines_fields = gdf_to_qgsfields(lines)
        lines_wkbtype = gdf_geom_to_qgs_wkbtype(lines)
        (sink_lignes, dest_id_lignes) = self.parameterAsSink(
            parameters, self.LIGNES, context,
            lines_fields, lines_wkbtype, crs
        )
        write_gdf_to_sink(lines, sink_lignes)
    
        # --- Sink noeuds ---
        nodes_fields = gdf_to_qgsfields(nodes)
        nodes_wkbtype = gdf_geom_to_qgs_wkbtype(nodes)
        (sink_noeuds, dest_id_noeuds) = self.parameterAsSink(
            parameters, self.NOEUDS, context,
            nodes_fields, nodes_wkbtype, crs
        )
        write_gdf_to_sink(nodes, sink_noeuds)
        return {self.LIGNES: dest_id_lignes, self.NOEUDS: dest_id_noeuds}

    def name(self): return "build_graph"
    def displayName(self): return "Construire le graphe réseau"
    def createInstance(self): return BuildGraphAlgorithm()
    def group(self): return "Réseau"
    def groupId(self): return "reseau"
    def tr(self, string):
        return QCoreApplication.translate('BuildGraphAlgorithm', string)