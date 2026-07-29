from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from .optimization_model import WorkplaceProblemData, WorkplaceItinerary, solve_workplace_model
from mobilityhubplugin.conversions import build_workplace_problem_data

class LocateHubsWorkplaceAlgorithm(QgsProcessingAlgorithm):
    """
    Miroir de LocateHubsPOIAlgorithm pour le modèle 'accessibilité aux emplois'
    (équations 13-21 de l'article). La structure est identique : seule la
    fonction objectif change (ratio temps voiture / temps trajet optimal,
    pondéré par le volume de commuting w_ij, cf. eq. 13), et il n'y a pas
    de seuil de temps de trajet (le modèle sélectionne toujours l'itinéraire
    le plus rapide, contrainte 15).

    À implémenter sur le même schéma que optimization_model.solve_poi_model :
    - Variables : y_lm, u_lm, e_l, x_s (pas de z_sp ni a_ip, cf. section 3.2.3)
    - Objectif : max somme(w_ij * r_s * x_s) / somme(w_ij)
    - Contraintes (14)-(21)
    """
    NODES = "NODES"
    HUBS = "HUBS"
    OD_MATRIX = "OD_MATRIX"
    BUDGET = "BUDGET"
    ITINERAIRES= "ITINERAIRES"
    OUTPUT = "OUTPUT"
    def createInstance(self):
        return LocateHubsWorkplaceAlgorithm()

    def name(self):
        return "locate_hubs_workplace"

    def displayName(self):
        return "Localiser les hubs (accessibilité emplois)"

    def group(self):
        return "Localisateur de Hubs"

    def groupId(self):
        return "mobility_hub"

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.NODES, "Nœuds de population (points)"))
        self.addParameter(QgsProcessingParameterFeatureSource(self.HUBS, "Hubs candidats (points)"))
        self.addParameter(QgsProcessingParameterFile(self.OD_MATRIX, "Matrice OD"))
        self.addParameter(QgsProcessingParameterFeatureSource(self.ITINERAIRES, 
                                                              "Itinéraires potentiels"))

        self.addParameter(QgsProcessingParameterNumber(self.BUDGET, "Budget (€)", defaultValue=150000))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Hubs sélectionnés"))

       
    def processAlgorithm(self, parameters, context, feedback):
        nodes_src = self.parameterAsSource(parameters, self.NODES, context)
        hubs_src = self.parameterAsSource(parameters, self.HUBS, context)
        budget = self.parameterAsDouble(parameters, self.BUDGET, context)
        od_src = self.parameterAsSource(parameters, self.OD_MATRIX, context)
        itineraries_src = self.parameterAsSource(parameters, self.ITINERAIRES, context)
        budget = self.parameterAsDouble(parameters, self.BUDGET, context)#float
        
        
        #od : origine_id, destination_id, volume => faire une fonction formatage
        
        feedback.pushInfo("Construction des data...")
        data = build_workplace_problem_data(
            nodes_src, hubs_src, itineraries_src, od_src,
            fixed_cost_hub=1000.0,
            fixed_cost_mode={"bs": 300.0, "cs": 7500.0, "pt": 0.0},
            budget=budget,
        )
        feedback.pushInfo(f"Modes détectés : {data.modes}")
        feedback.pushInfo(f"{len(data.itineraries)} itinéraires potentiels générés. Résolution du MIP...")
        result = solve_workplace_model(data, time_limit_s=300)
        feedback.pushInfo(f"Statut : {result['status']} — accessibilité obtenue : {result['objective']:.3f}")

        fields = QgsFields()
        fields.append(QgsField("hub_id", QVariant.String))
        fields.append(QgsField("mode", QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point, hubs_src.sourceCrs()
        )

        hub_features = {f["id"]: f for f in hubs_src.getFeatures()}
        for (hub_id, mode) in result["hubs"]:
            src_feat = hub_features.get(hub_id)
            if src_feat is None:
                continue
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(src_feat.geometry())
            out_feat.setAttributes([hub_id, mode])
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}