import json
import argparse
import math
import queue
import re
import socket
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from statistics import median
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

try:
    # Use the shared project implementation when this file is run in AI-ProGait.
    from backend.fsr_force import matrix_to_newton
except (ImportError, ModuleNotFoundError):
    # Standalone fallback: keep this app usable when only FSR_Transmitter.py is
    # copied to another Windows computer. Keep these constants synchronized
    # with backend/fsr_force.py.
    def _analog_to_weight_smooth(adc):
        value = float(adc)
        if value >= 4950.0:
            return 0.0
        if value > 680.0:
            return max(0.0, -0.0868 * value + 434.03)
        return 132728.45 * value ** (-0.889) if value > 0 else 0.0

    def _gram_to_newton(gram):
        return max(0.0, float(gram) * 9.80665 / 1000.0)

    def matrix_to_newton(matrix, unit):
        normalized_unit = str(unit or "raw_adc").strip().lower()
        values = [[float(value) for value in row] for row in matrix]
        if normalized_unit == "newton":
            return (
                [[max(0.0, value) for value in row] for row in values],
                "N",
                "packet",
            )
        if normalized_unit == "gram":
            force_values = [
                [_gram_to_newton(value) for value in row]
                for row in values
            ]
        else:
            force_values = [
                [_gram_to_newton(_analog_to_weight_smooth(value)) for value in row]
                for row in values
            ]
        return force_values, "N_estimated", "formula_estimate"

try:
    from backend.fsi_phase_metrics import (
        DEFAULT_FSI_ROIS,
        FsiSessionAnalyzer,
        FOREFOOT_CELL_IDS,
        HEEL_CELL_IDS,
        STANCE_CELL_IDS,
    )
except (ImportError, ModuleNotFoundError):
    DEFAULT_FSI_ROIS = {}
    FOREFOOT_CELL_IDS = ()
    HEEL_CELL_IDS = ()
    STANCE_CELL_IDS = ()
    FsiSessionAnalyzer = None

DEFAULT_TARGET_IP = "127.0.0.1"
# Specimen-specific experimental calibration. NOT validated full-range force.
# Old 85 cells retained; 11 retested cells fit median of per-placement medians.
# Retest baseline: elapsed 8–25s; windows trim first 2s and last 1s of >4N runs.
# Retest source SHA256: fa6d70f994d9893835e4e2fa3963e37ac63c57d7a71f5b40dc2be7d566ba2f5c
BUILTIN_CELL_CALIBRATIONS = {
    'right': {
        'version': 1,
        'id': "right-20260928-repeat-median-v2",
        'side': "right",
        'status': "provisional_single_point_not_validated",
        'cells': [
            [{"baseline_n":0.5430203073875562,"gain":1.8013744974704866},{"baseline_n":0.5270696104787869,"gain":1.564884242034935},{"baseline_n":0.4839518626325734,"gain":1.5675683237163553},{"baseline_n":0.5434151153546811,"gain":1.6008665557551043}],
            [{"baseline_n":0.26570412789584275,"gain":1.3603235524351602},{"baseline_n":0.5905929718897815,"gain":1.1660506137019246},{"baseline_n":0.6940988165033128,"gain":1.1232186763109593},{"baseline_n":0.728401844311139,"gain":1.4677557058745}],
            [{"baseline_n":0.49955472296195863,"gain":1.3569836015003485},{"baseline_n":0.6721615393219712,"gain":1.1273455058423436},{"baseline_n":0.6678919481743208,"gain":1.1299192465070786},{"baseline_n":0.7671502706009586,"gain":1.1269080197942116}],
            [{"baseline_n":0.5181801332351436,"gain":1.3118674464354878},{"baseline_n":0.561591285443074,"gain":1.39535164968139},{"baseline_n":0.7047692372828768,"gain":0.9196655950333367},{"baseline_n":0.5423607896696118,"gain":1.1076027023753994}],
            [{"baseline_n":0.4846638466278961,"gain":1.046033111176853},{"baseline_n":0.5319404463860747,"gain":1.5316153146532927},{"baseline_n":0.5133557746012489,"gain":0.8643267473097201},{"baseline_n":0.5768396217016878,"gain":0.9018983748087714}],
            [{"baseline_n":0.4618621634481451,"gain":1.237275849522209},{"baseline_n":0.6736356082049602,"gain":0.9830445271228363},{"baseline_n":0.7194774980498975,"gain":1.2358393827655232},{"baseline_n":0.7173010386474274,"gain":0.9986097961597793}],
            [{"baseline_n":0.36255170304822415,"gain":1.2286019581624001},{"baseline_n":0.30830691040810343,"gain":1.2271102332121395},{"baseline_n":0.5907326446104195,"gain":1.1440729094919235},{"baseline_n":0.6625523393594691,"gain":0.9578127419575424}],
            [{"baseline_n":0.3969327862705283,"gain":1.250727630230439},{"baseline_n":0.5788256517653116,"gain":1.159123817826331},{"baseline_n":0.6473372872191471,"gain":1.1494744758015447},{"baseline_n":0.6941028146859205,"gain":1.141373477151277}],
            [{"baseline_n":0.45882628342558396,"gain":0.9785493092987164},{"baseline_n":0.5074731083692766,"gain":1.3436421880460516},{"baseline_n":0.6298149822299066,"gain":1.1282433342895721},{"baseline_n":0.5090087825049349,"gain":1.1407255899069726}],
            [{"baseline_n":0.5095629528286183,"gain":1.3539094542531194},{"baseline_n":0.6181493517247665,"gain":1.0407702287439655},{"baseline_n":0.6700779511275171,"gain":1.4900730614199158},{"baseline_n":0.6268323898517693,"gain":1.1777344578778153}],
            [{"baseline_n":0.41288389127063196,"gain":1.2954490088242783},{"baseline_n":0.5284537118455944,"gain":1.4234374250491602},{"baseline_n":0.8262914943962365,"gain":1.2576707270313392},{"baseline_n":0.8250167150100495,"gain":1.4953846236339419}],
            [{"baseline_n":0.47875750065882877,"gain":1.4332826326492871},{"baseline_n":0.6050177654872857,"gain":1.270663606196705},{"baseline_n":0.44600001639512393,"gain":1.2546366643795694},{"baseline_n":0.5809428208348044,"gain":1.3735846659920514}],
        ],
    },
    'left': {
        'version': 1,
        'id': "left-20260928-repeat-median-v2",
        'side': "left",
        'status': "provisional_single_point_not_validated",
        'cells': [
            [{"baseline_n":0.6747425939608492,"gain":2.2015896767379872},{"baseline_n":0.7293564252340441,"gain":1.870214316689304},{"baseline_n":0.9092848676350717,"gain":1.4917295000762558},{"baseline_n":0.7814698458101734,"gain":1.5386909517927039}],
            [{"baseline_n":0.7514151531921152,"gain":1.075874329175584},{"baseline_n":0.7156104030547352,"gain":1.4161544979147653},{"baseline_n":0.7432409188690317,"gain":1.5726115225135602},{"baseline_n":0.6598197633364733,"gain":1.5606816095650975}],
            [{"baseline_n":0.7792955572390036,"gain":1.290963330204433},{"baseline_n":0.7752298515643177,"gain":1.41868070963739},{"baseline_n":0.7490703797951669,"gain":1.6660799426394477},{"baseline_n":0.6795122597733931,"gain":1.3160971569399258}],
            [{"baseline_n":0.7746726305287819,"gain":1.077748305930369},{"baseline_n":1.6285659696224144,"gain":1.2281289813811367},{"baseline_n":0.9601863947424305,"gain":1.0765353523175751},{"baseline_n":0.6670238016332709,"gain":1.4377994112449306}],
            [{"baseline_n":0.7522853860380336,"gain":1.322559166995866},{"baseline_n":0.7328249780304796,"gain":0.9664212188101504},{"baseline_n":0.7194898408532964,"gain":1.1482205497527311},{"baseline_n":0.7334759295766622,"gain":1.3948443179957803}],
            [{"baseline_n":0.7790283866260328,"gain":1.1600315877932428},{"baseline_n":0.8050897091232136,"gain":1.2735109880224953},{"baseline_n":0.7134501222002907,"gain":1.2669196232691864},{"baseline_n":0.6572089427145351,"gain":1.3015426673607335}],
            [{"baseline_n":0.7228875582295817,"gain":1.1259507192260358},{"baseline_n":0.7095040457169591,"gain":1.3437847460808445},{"baseline_n":0.6822353087969032,"gain":1.5348804358770227},{"baseline_n":0.723991406968182,"gain":1.1988830056350632}],
            [{"baseline_n":0.7354589971085301,"gain":1.4507465239211834},{"baseline_n":0.8727116147288391,"gain":1.5020899536900616},{"baseline_n":0.7403439562692353,"gain":1.0780095521738848},{"baseline_n":1.2377455978654868,"gain":1.350456628883831}],
            [{"baseline_n":0.7885064732080234,"gain":1.3045739959593095},{"baseline_n":0.7453282179088803,"gain":1.261561849667097},{"baseline_n":0.6500113634464999,"gain":1.1374369468231464},{"baseline_n":0.6170607176872606,"gain":1.2274979324014361}],
            [{"baseline_n":0.7919427355127138,"gain":1.1877269170641123},{"baseline_n":0.7414806932906217,"gain":1.0616803390853882},{"baseline_n":0.7275988959147199,"gain":1.1345616139053516},{"baseline_n":0.7242314554132802,"gain":1.2868168535148774}],
            [{"baseline_n":0.7999246867226895,"gain":1.510591029137182},{"baseline_n":0.792103751688313,"gain":1.469825934956434},{"baseline_n":0.9983579123462586,"gain":1.1186534301311135},{"baseline_n":1.1311767021202301,"gain":1.1735022893328924}],
            [{"baseline_n":0.7553508713397734,"gain":1.3003324665777165},{"baseline_n":0.8922631851296361,"gain":1.2793985252416855},{"baseline_n":0.8083502046752187,"gain":1.3331189301577855},{"baseline_n":0.6532643421449854,"gain":1.2764652277242219}],
        ],
    },
}
RETEST_CALIBRATION_AUDIT = {
    'right': [
        {"row":1,"column":1,"windows_s":[[33.406,39.203],[44.015,46.422],[65.25,69.234],[83.328,86.531]],"trial_medians_n":[8.038301111204364,8.476684935679167,9.362187401587416,8.592886277775207],"corrected_range_n":[13.501807691375685,15.886622692422526]},
        {"row":1,"column":2,"windows_s":[[54.75,58.547],[76.125,78.14],[92.703,100.531],[105.093,107.937],[113.64,120.875]],"trial_medians_n":[11.302577593674616,10.329852690235672,8.562316701416488,8.97379721471808,9.726575754958587],"corrected_range_n":[12.574231553465461,16.862422642824797]},
        {"row":2,"column":4,"windows_s":[[127.453,137.968],[145.453,151.922],[158.453,161.062],[165.218,174.656]],"trial_medians_n":[8.290727307639491,11.637122408121316,10.253391743286961,10.819976394556999],"corrected_range_n":[11.099646348480212,16.01133685132288]},
        {"row":4,"column":2,"windows_s":[[180.968,186.218],[203.562,210.703],[226.593,238.656]],"trial_medians_n":[13.060180667211565,9.753676692331588,10.878820066651862],"corrected_range_n":[12.82619153651412,17.43992731254097]},
        {"row":4,"column":3,"windows_s":[[191.265,198.203],[215.922,221.187],[243.453,256.109]],"trial_medians_n":[15.304606495178763,16.937998777099533,16.358461489930598],"corrected_range_n":[13.4269680191727,14.929142704048221]},
        {"row":5,"column":4,"windows_s":[[261.75,269.453],[276.359,285.5],[292.156,300.703],[309.484,327.5],[339.343,356.515]],"trial_medians_n":[16.538906526470644,14.354452015477417,16.38304782294074,17.956320721117045,17.61319539551387],"corrected_range_n":[12.426006226691518,15.674525758582472]},
        {"row":10,"column":3,"windows_s":[[365.484,373.047],[393.906,398.39],[439.172,443.781],[457.437,462.875]],"trial_medians_n":[10.661414219323756,9.919694816316706,11.852681627826172,10.001501851861056],"corrected_range_n":[13.782604919273739,16.662896495183972]},
        {"row":10,"column":4,"windows_s":[[378.125,383.109],[448.547,452.922],[467.328,473.765]],"trial_medians_n":[13.696783952695487,12.259961513939263,12.850438571792603],"corrected_range_n":[13.700737022379808,15.39293231835505]},
    ],
    'left': [
        {"row":1,"column":1,"windows_s":[[481.078,488.515],[506.218,515.453],[533.578,546.359]],"trial_medians_n":[7.213727742787607,6.922017886387136,7.394752658861412],"corrected_range_n":[13.753936791546003,14.79470478646045]},
        {"row":1,"column":3,"windows_s":[[493.922,501.047],[520.531,527.531],[551.422,572.922]],"trial_medians_n":[10.559936811746976,10.267004081401904,11.54252168634013],"corrected_range_n":[13.959185804606372,15.861913043759335]},
        {"row":11,"column":2,"windows_s":[[580.062,594.859],[602.531,608.531],[622.328,632.047],[642.547,650.937],[662.328,674.312]],"trial_medians_n":[9.641150793692146,12.319712934570607,10.586571149235427,11.063144770537374,9.696329598548708],"corrected_range_n":[13.006558841986752,16.943578945042344]},
    ],
}
# Quick provisional refit from 2.jsonl: ONLY 1468g; H1C1 first placement rejected by user.
# Stable means (P90-P10)/median <= 10%; trim 3s start / 1s end; no full-range validation.
RIGHT_REFIT_20260929 = [
    {"row":1,"column":1,"old_gain":1.8013744974704866,"gain":1.4365065005780648,"measured_n":18.0527407555016,"window_s":[14.5,21.10900000000038]},
    {"row":1,"column":2,"old_gain":1.564884242034935,"gain":1.4367073196156284,"measured_n":15.680526621515458,"window_s":[26.875,30.5]},
    {"row":1,"column":4,"old_gain":1.6008665557551043,"gain":1.3431685392270685,"measured_n":17.15818523449628,"window_s":[47.01599999999962,51.01599999999962]},
    {"row":2,"column":1,"old_gain":1.3603235524351602,"gain":1.5455113592442062,"measured_n":12.671170864065056,"window_s":[60.79700000000048,63.78099999999904]},
    {"row":2,"column":2,"old_gain":1.1660506137019246,"gain":1.0339769979123605,"measured_n":16.23503598450967,"window_s":[69.9369999999999,73.84399999999914]},
    {"row":2,"column":3,"old_gain":1.1232186763109593,"gain":1.330271642825215,"measured_n":12.155440836053705,"window_s":[83.70299999999952,86.90599999999904]},
    {"row":2,"column":4,"old_gain":1.4677557058745,"gain":1.7129611154059536,"measured_n":12.335393385002318,"window_s":[93.3119999999999,97.875]},
    {"row":4,"column":2,"old_gain":1.39535164968139,"gain":1.1002386228311762,"measured_n":18.257592723986008,"window_s":[161.375,165.26599999999962]},
    {"row":4,"column":4,"old_gain":1.1076027023753994,"gain":1.2744452088276381,"measured_n":12.511505434762931,"window_s":[186.46899999999914,193.76599999999962]},
    {"row":5,"column":1,"old_gain":1.046033111176853,"gain":1.2101359353788095,"measured_n":12.443942779336378,"window_s":[199.79700000000048,206.73400000000038]},
    {"row":5,"column":2,"old_gain":1.5316153146532927,"gain":1.2860242982344152,"measured_n":17.145385610539762,"window_s":[212.79700000000048,218.53099999999904]},
    {"row":5,"column":4,"old_gain":0.9018983748087714,"gain":1.0468656383169839,"measured_n":12.402618651747202,"window_s":[240.09399999999914,245.70299999999952]},
    {"row":6,"column":3,"old_gain":1.2358393827655232,"gain":1.1469495969277146,"measured_n":15.511879733073954,"window_s":[281.125,287.03099999999904]},
    {"row":6,"column":4,"old_gain":0.9986097961597793,"gain":1.1731139013987668,"measured_n":12.25469119655275,"window_s":[292.03099999999904,300.3590000000004]},
    {"row":7,"column":1,"old_gain":1.2286019581624001,"gain":0.889373502606888,"measured_n":19.887204888722017,"window_s":[306.2029999999995,311.5159999999996]},
    {"row":7,"column":4,"old_gain":0.9578127419575424,"gain":1.08751804990221,"measured_n":12.679171248410471,"window_s":[335.7659999999996,340.9220000000005]},
    {"row":8,"column":2,"old_gain":1.159123817826331,"gain":1.0168707114538187,"measured_n":16.41008468761365,"window_s":[363.6090000000004,371.2970000000005]},
    {"row":8,"column":3,"old_gain":1.1494744758015447,"gain":1.101382406136647,"measured_n":15.02477332686384,"window_s":[377.53099999999904,383.4840000000004]},
    {"row":9,"column":1,"old_gain":0.9785493092987164,"gain":1.234976592978956,"measured_n":11.406981037091072,"window_s":[402,409.0619999999999]},
    {"row":9,"column":2,"old_gain":1.3436421880460516,"gain":1.202130843286199,"measured_n":16.090836522417284,"window_s":[414.1869999999999,423.8119999999999]},
    {"row":9,"column":3,"old_gain":1.1282433342895721,"gain":1.3131823003836878,"measured_n":12.368712277614296,"window_s":[429.0779999999995,436]},
    {"row":9,"column":4,"old_gain":1.1407255899069726,"gain":1.0424271108951562,"measured_n":15.753687184794577,"window_s":[442.0470000000005,464.4220000000005]},
    {"row":10,"column":1,"old_gain":1.3539094542531194,"gain":1.263289222802502,"measured_n":15.428850144309788,"window_s":[470.5619999999999,483.0470000000005]},
    {"row":10,"column":2,"old_gain":1.0407702287439655,"gain":1.1986073842779723,"measured_n":12.500421090726785,"window_s":[487.8119999999999,495.34399999999914]},
    {"row":11,"column":2,"old_gain":1.4234374250491602,"gain":0.9214735109774514,"measured_n":22.238334372543342,"window_s":[539.625,547.7659999999996]},
    {"row":11,"column":3,"old_gain":1.2576707270313392,"gain":1.0910354892496121,"measured_n":16.59490636091746,"window_s":[552.4369999999999,557.125]},
    {"row":11,"column":4,"old_gain":1.4953846236339419,"gain":1.2709252104420932,"measured_n":16.938683265029972,"window_s":[561.9689999999991,566.030999999999]},
    {"row":12,"column":1,"old_gain":1.4332826326492871,"gain":1.2247248394321049,"measured_n":16.847677611919643,"window_s":[572.030999999999,578.0779999999995]},
    {"row":12,"column":3,"old_gain":1.2546366643795694,"gain":1.1963720688832922,"measured_n":15.097270650370902,"window_s":[598.125,604.530999999999]},
    {"row":12,"column":4,"old_gain":1.3735846659920514,"gain":1.1326531054550906,"measured_n":17.458432376000264,"window_s":[609.5619999999999,612.5159999999996]},
]
for _fit in RIGHT_REFIT_20260929:
    BUILTIN_CELL_CALIBRATIONS['right']['cells'][_fit['row']-1][_fit['column']-1]['gain'] = _fit['gain']
BUILTIN_CELL_CALIBRATIONS['right']['id'] = 'right-20260929-single-load-v3'
# Provisional three-anchor refit: check.jsonl, filtered ADC -> legacy N minus
# existing baseline. Only the two loading holds fit the curve; unloading is
# a same-cycle check, NOT independent validation. No new live shoe tare.
# Targets assume 1468g and approximately 333.3g; small weight not certified.
# Outside the measured interval retain previous gain, not a validated range.
# Source SHA256: b91b473856b7d2a82988f9cbe89e34b10c98cf0577aa552d9f3cb5e782c9dafe
RIGHT_THREE_POINT_20260929 = [
    {"row":1,"column":1,"points_n":[[0,0],[9.360848730714954,14.3961622],[11.138778653745558,17.664718645]],"windows_s":[[10,13],[19,23],[25,27]],"return_input_n":9.465529657083524},
    {"row":1,"column":2,"points_n":[[0,0],[10.95228890695742,14.3961622],[13.446527279254138,17.664718645]],"windows_s":[[36,40],[44,48],[50,53]],"return_input_n":10.841306469025277},
    {"row":1,"column":3,"points_n":[[0,0],[9.06936886403129,14.3961622],[10.978806319801134,17.664718645]],"windows_s":[[64,68],[75,80],[83,86]],"return_input_n":9.60731440020786},
    {"row":1,"column":4,"points_n":[[0,0],[9.750660732815716,14.3961622],[12.964217215607764,17.664718645]],"windows_s":[[97,102],[108,112],[114,117]],"return_input_n":10.026271061072462},
    {"row":2,"column":2,"points_n":[[0,0],[15.303278005210892,14.3961622],[17.811387064152022,17.664718645]],"windows_s":[[160,165],[172,177],[181,185]],"return_input_n":14.719255495690785},
    {"row":2,"column":4,"points_n":[[0,0],[8.679548698323968,14.3961622],[11.147654522453768,17.664718645]],"windows_s":[[242,248],[254,260],[264,268]],"return_input_n":8.941786386325193},
    {"row":3,"column":1,"points_n":[[0,0],[11.647684112260489,14.3961622],[14.23632636429668,17.664718645]],"windows_s":[[279,283],[290,295],[300,304]],"return_input_n":11.943312050125922},
    {"row":3,"column":2,"points_n":[[0,0],[12.147310868739337,14.3961622],[14.972892849897024,17.664718645]],"windows_s":[[322,327],[332,337],[340,344]],"return_input_n":12.640077580210868},
    {"row":3,"column":3,"points_n":[[0,0],[14.404163942269767,14.3961622],[16.833834671068036,17.664718645]],"windows_s":[[353,357],[364,369],[373,377]],"return_input_n":15.018556033129153},
    {"row":3,"column":4,"points_n":[[0,0],[12.290458688098859,14.3961622],[14.523766623050351,17.664718645]],"windows_s":[[393,398],[405,410],[415,419]],"return_input_n":12.73075013503053},
    {"row":4,"column":1,"points_n":[[0,0],[8.19813054869444,14.3961622],[10.976423453994107,17.664718645]],"windows_s":[[430,435],[440,445],[449,453]],"return_input_n":8.940100608771683},
    {"row":4,"column":2,"points_n":[[0,0],[10.24632007129055,14.3961622],[13.319469827031629,17.664718645]],"windows_s":[[470,474],[478,482],[486,489]],"return_input_n":10.48904934420391},
    {"row":4,"column":3,"points_n":[[0,0],[15.939218820419802,14.3961622],[17.48691199452025,17.664718645]],"windows_s":[[502,507],[514,519],[523,527]],"return_input_n":16.125300741837634},
    {"row":4,"column":4,"points_n":[[0,0],[11.586443532095123,14.3961622],[14.912070874995232,17.664718645]],"windows_s":[[535,539],[544,548],[551,554]],"return_input_n":12.170237640459884},
    {"row":5,"column":1,"points_n":[[0,0],[12.727532573402522,14.3961622],[15.75759057304759,17.664718645]],"windows_s":[[566,570],[576,580],[582,586]],"return_input_n":13.388409941321797},
    {"row":5,"column":2,"points_n":[[0,0],[8.371156269437689,14.3961622],[11.00393055472572,17.664718645]],"windows_s":[[598,602],[611,616],[620,623]],"return_input_n":8.822749370992303},
    {"row":5,"column":3,"points_n":[[0,0],[14.447428755492831,14.3961622],[17.164376507495135,17.664718645]],"windows_s":[[634,638],[643,647],[650,654]],"return_input_n":14.110702174156314},
    {"row":6,"column":2,"points_n":[[0,0],[13.184073717035979,14.3961622],[15.409655686766007,17.664718645]],"windows_s":[[737,741],[748,753],[757,760]],"return_input_n":12.91142155080393},
]
RIGHT_THREE_POINT_RETEST_CELLS = [(2, 1), (2, 3), (5, 4), (6, 1)]
for _fit in RIGHT_THREE_POINT_20260929:
    BUILTIN_CELL_CALIBRATIONS['right']['cells'][_fit['row']-1][_fit['column']-1]['points_n'] = _fit['points_n']
BUILTIN_CELL_CALIBRATIONS['right']['id'] = 'right-20260929-three-point-v4'
BUILTIN_CELL_CALIBRATIONS['right']['status'] = 'provisional_mixed_three_point_not_validated'
CELL_CALIBRATIONS = BUILTIN_CELL_CALIBRATIONS
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20
DEFAULT_BAUDRATE = 9600
DEFAULT_SERIAL_TIMEOUT = 0.5
MIN_FORCE = 30.0
MAX_FORCE = 5500.0
CHART_WINDOW_SECONDS = 30.0
CHART_MAX_POINTS = 6000
FSI_CONTACT_THRESHOLD_N = 5.0
FSI_DEBOUNCE_SAMPLES = 2
CHART_COLORS = {
    "left": "#2563eb",
    "right": "#ef4444",
    "heel": "#2563eb",
    "midfoot": "#0f9d8a",
    "forefoot": "#ea6a14",
}


def is_outgoing_bluetooth_port(port_info):
    """Windows Bluetooth SPP uses LOCALMFG&0002 for the connect-out port."""
    return "LOCALMFG&0002" in str(getattr(port_info, "hwid", "")).upper()


def selectable_fsr_ports(port_infos):
    """Return ports that can actually connect to FSR modules, never SPP input."""
    infos = list(port_infos)
    outgoing = [item for item in infos if is_outgoing_bluetooth_port(item)]
    if outgoing:
        return outgoing
    return [
        item for item in infos
        if "LOCALMFG&0000" not in str(getattr(item, "hwid", "")).upper()
    ]

INDEX_MAP_RR = [
    [  36,     24,     12,     0  ],
    [  47,     35,     23,     11 ],
    [  37,     25,     13,     1  ],
    [  46,     34,     22,     10 ],
    [  38,     26,     14,     2  ],
    [  45,     33,     21,     9  ],
    [  39,     27,     15,     3  ],
    [  44,     32,     20,     8  ],
    [  40,     28,     16,     4  ],
    [  43,     31,     19,     7  ],
    [  41,     29,     17,     5  ],
    [  42,     30,     18,     6  ],
]

INDEX_MAP_LL = [row[::-1] for row in INDEX_MAP_RR]


def get_force_color(value, min_val=MIN_FORCE, max_val=MAX_FORCE):
    if value < min_val:
        return "#111827"

    t = min(max((value - min_val) / (max_val - min_val), 0.0), 1.0)

    if t < 0.5:
        red = 255
        green = int(255 * (t / 0.5))
        blue = 0
    else:
        red = int(255 * ((1.0 - t) / 0.5))
        green = 255
        blue = 0

    return f"#{red:02x}{green:02x}{blue:02x}"


def validate_matrix(matrix):
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("Ma trận không hợp lệ")
    if not isinstance(matrix[0], list) or not matrix[0]:
        raise ValueError("Ma trận không hợp lệ")

    columns = len(matrix[0])
    normalized = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError("Cột không nhất quán")
        normalized_row = []
        for value in row:
            if not isinstance(value, (int, float)):
                raise ValueError("Giá trị phải là số")
            if value < 0:
                raise ValueError("Giá trị không được âm")
            normalized_row.append(float(value))
        normalized.append(normalized_row)
    return normalized


def unit_label(unit):
    return {
        'raw_adc': 'ADC thô',
        'newton': 'Newton (N, ước tính)',
    }.get(str(unit).strip().lower(), 'ADC thô')


def calibration_metadata(side, unit):
    profile = CELL_CALIBRATIONS.get(side) if unit == 'newton' else None
    return {
        'calibration_id': profile['id'] if profile else None,
        'calibration_status': profile['status'] if profile else None,
    }


def matrix_for_unit(raw_adc_matrix, unit, side=None, profile=None):
    '''Convert raw ADC values to the unit selected for preview and UDP.'''
    raw_adc_matrix = validate_matrix(raw_adc_matrix)
    if str(unit).strip().lower() == 'newton':
        force_matrix, _, _ = matrix_to_newton(raw_adc_matrix, 'raw_adc')
        selected_profile = profile if profile is not None else CELL_CALIBRATIONS.get(side)
        if selected_profile is not None and side == selected_profile.get('side'):
            from backend.fsr_force import apply_cell_calibration
            return apply_cell_calibration(force_matrix, side, selected_profile)
        return force_matrix
    return [row[:] for row in raw_adc_matrix]


def color_range_for_unit(unit):
    if str(unit).strip().lower() == 'newton':
        return 0.05, 80.0
    return MIN_FORCE, MAX_FORCE


def parse_hardware_frame(values_list, side, expected_rows=None, expected_columns=None):
    total_values = len(values_list)
    if total_values == 0:
        raise ValueError("Không tìm thấy dữ liệu")

    if total_values == 48:
        mapping = INDEX_MAP_LL if side == "left" else INDEX_MAP_RR
        matrix = []
        for row_indices in mapping:
            row_vals = [values_list[idx] for idx in row_indices]
            matrix.append(row_vals)
    else:
        rows = expected_rows or 12
        cols = expected_columns or 4
        if total_values != rows * cols:
            raise ValueError(
                f"Nhận được {total_values} giá trị, cần {rows * cols}"
            )
        matrix = [
            values_list[r * cols : (r + 1) * cols]
            for r in range(rows)
        ]

    return validate_matrix(matrix), side


def matrix_summary(matrix):
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return total, None, None
    weighted_x = 0.0
    weighted_y = 0.0
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            weighted_x += x * value
            weighted_y += y * value
    return total, weighted_x / total, weighted_y / total


def matrix_region_totals(matrix):
    """Split a 12-row insole like the main backend: forefoot 0:4, mid 4:9, heel 9:12."""
    rows = validate_matrix(matrix)
    row_count = len(rows)
    forefoot_end = max(1, round(row_count * 4 / 12))
    midfoot_end = max(forefoot_end + 1, round(row_count * 9 / 12))
    midfoot_end = min(midfoot_end, row_count)

    def total(first_row, last_row):
        return sum(sum(row) for row in rows[first_row:last_row])

    heel = total(midfoot_end, row_count)
    midfoot = total(forefoot_end, midfoot_end)
    forefoot = total(0, forefoot_end)
    return {
        "heel": heel,
        "midfoot": midfoot,
        "forefoot": forefoot,
        "total": heel + midfoot + forefoot,
    }


def nice_axis_max(value, minimum):
    """Round a chart ceiling to a readable 1/2/5 × 10^n value."""
    target = max(float(value) * 1.12, float(minimum))
    exponent = 10 ** math.floor(math.log10(target)) if target > 0 else 1.0
    normalized = target / exponent
    step = 1.0 if normalized <= 1 else 2.0 if normalized <= 2 else 5.0 if normalized <= 5 else 10.0
    return step * exponent


def build_packet(device_id, side, unit, sequence, matrix):
    return {
        "type": "fsr_matrix",
        "version": 1,
        "device_id": device_id,
        "side": side,
        "unit": unit,
        "sequence": sequence,
        "timestamp_ms": int(time.time() * 1000),
        "rows": len(matrix),
        "columns": len(matrix[0]),
        "values": matrix,
    }


class ShoeZero:
    """Session-only tare of calibrated Newton, never of raw ADC or old logs.

    Stability/noise limits are provisional screening settings, not accuracy
    claims. A stable loaded foot cannot be detected: operator must unload it.
    All state is locked because two serial workers and Tk share this object.
    """
    duration = 3.0
    fresh_seconds = 0.5

    def __init__(self):
        self.lock = threading.RLock()
        self.profiles = {}
        self.latest = {}
        self.pending = None
        self.revision = 0

    def state(self):
        with self.lock:
            return tuple(sorted(self.profiles)), self.pending is not None

    def is_current(self, metadata):
        with self.lock:
            return metadata.get('zero_revision') == self.revision

    def reset(self):
        with self.lock:
            self.profiles.clear()
            self.latest.clear()
            self.pending = None
            self.revision += 1

    def start(self, sides, now):
        with self.lock:
            sides = tuple(sides)
            if not sides or any(s not in ('left', 'right') for s in sides):
                raise ValueError('Chọn chân trái, phải hoặc cả hai.')
            if self.pending is not None:
                raise ValueError('Đang thu mẫu zero.')
            if any(s not in self.latest or not 0 <= now-self.latest[s] <= self.fresh_seconds
                   for s in sides):
                raise ValueError('Thiếu dữ liệu mới ở chân đã chọn. Kiểm tra kết nối FSR.')
            self.pending = {'start': now, 'samples': {s: [] for s in sides}}

    def process(self, side, matrix, now):
        values = validate_matrix(matrix)
        if any(not math.isfinite(v) for row in values for v in row):
            raise ValueError('Dữ liệu FSR không hữu hạn; không thể lấy zero.')
        with self.lock:
            self.latest[side] = now
            if (self.pending is not None and side in self.pending['samples']
                    and 0 <= now-self.pending['start'] <= self.duration):
                self.pending['samples'][side].append((now, values))
            profile = self.profiles.get(side)
            meta = {'zero_applied': profile is not None,
                    'zero_revision': self.revision,
                    'zero_collecting': self.pending is not None}
            if profile is None:
                return values, meta
            baseline, noise = profile['baseline'], profile['noise']
            if len(values) != len(baseline) or any(len(a) != len(b) for a, b in zip(values, baseline)):
                raise ValueError('Kích thước FSR thay đổi; huỷ zero rồi lấy lại.')
            result = [[max(0.0, v-b) if v-b > n else 0.0
                       for v, b, n in zip(row, base, band)]
                      for row, base, band in zip(values, baseline, noise)]
            meta.update(zero_baseline_n=[r[:] for r in baseline],
                        zero_noise_n=[r[:] for r in noise],
                        zero_method='calibrated_newton_median_deadband_v1')
            return result, meta

    def finish(self, now):
        with self.lock:
            pending, self.pending = self.pending, None
            if pending is None:
                raise ValueError('Không có lượt lấy zero đang chạy.')
            fitted = {}
            for side, samples in pending['samples'].items():
                if (now-pending['start'] < self.duration or len(samples) < 20
                        or samples[-1][0]-samples[0][0] < 2.5
                        or now-samples[-1][0] > self.fresh_seconds
                        or any(b[0]-a[0] > self.fresh_seconds for a, b in zip(samples, samples[1:]))):
                    raise ValueError('Mẫu zero thiếu hoặc gián đoạn. Nhấc chân, giữ yên và thử lại.')
                shape = [len(row) for row in samples[0][1]]
                if any([len(row) for row in m] != shape for _, m in samples):
                    raise ValueError('Kích thước FSR thay đổi trong lúc lấy zero.')
                baseline, noise = [], []
                for r, columns in enumerate(shape):
                    base_row, noise_row = [], []
                    for c in range(columns):
                        data = [m[r][c] for _, m in samples]
                        ordered = sorted(data)
                        center = median(data)
                        spread = ordered[int(.9*(len(data)-1))]-ordered[int(.1*(len(data)-1))]
                        drift = abs(median(data[:len(data)//2])-median(data[len(data)//2:]))
                        # Reject movement instead of hiding it in a large deadband.
                        if spread > max(1.0, .2*center) or drift > max(.3, .1*center):
                            raise ValueError(f'{side}: H{r+1}C{c+1} chưa ổn định. Giữ yên và lấy zero lại.')
                        deviations = sorted(abs(v-center) for v in data)
                        base_row.append(center)
                        noise_row.append(max(.02, deviations[int(.95*(len(data)-1))]))
                    baseline.append(base_row)
                    noise.append(noise_row)
                fitted[side] = {'baseline': baseline, 'noise': noise}
            # Atomic: failure on either foot leaves all previous profiles intact.
            self.profiles.update(fitted)
            self.revision += 1


class FSRTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FSR Matrix Transmitter V3 · FSI theo pha")
        self.root.geometry("1320x860")
        self.root.minsize(1080, 700)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serial_connections = {}
        self.serial_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.running = False
        self.workers = []
        self.active_channels = set()
        self.connected_channels = set()
        self.detected_sides = {}
        self.frame_counts = {1: 0, 2: 0}
        self.ema_alpha = tk.DoubleVar(value=0.20)
        self.ema_alpha_value = 0.20
        self.ema_label_text = tk.StringVar(value='EMA alpha: 0.20')
        self.smoothed_matrices = {}
        self.last_raw_matrices = {}
        self.shoe_zero = ShoeZero()
        self.zero_after_id = None
        self.zero_started_at = None
        self.zero_button_text = tk.StringVar(value='Zero hết')
        self.zero_status = tk.StringVar(value='Chưa zero · chỉ áp dụng dữ liệu trực tiếp (Newton)')
        self.chart_history = {
            "left": deque(maxlen=CHART_MAX_POINTS),
            "right": deque(maxlen=CHART_MAX_POINTS),
        }
        self.chart_started_at = time.monotonic()
        self.chart_unit = "newton"
        self.chart_redraw_pending = False
        self.total_chart_canvas = None
        self.region_chart_canvas = None
        self.fsi_analyzer = (
            FsiSessionAnalyzer(FSI_CONTACT_THRESHOLD_N, FSI_DEBOUNCE_SAMPLES)
            if FsiSessionAnalyzer is not None else None
        )
        self.fsi_last_refresh = 0.0
        self.fsi_status = tk.StringVar(value="FSI: đang chờ đủ cặp bước")
        self.fsi_register_text = tk.StringVar(value="Đăng ký ROI sau khi căn dấu chân")
        self.fsi_roi_registered = False
        self.fsi_tree = None
        self.fsi_summary_tree = None
        self.fsi_trend_canvas = None

        self.log_lock = threading.Lock()
        self.log_handle = None
        self.log_path = None
        self.log_started_at = None
        self.log_sample_count = 0

        self.playback_records = []
        self.playback_index = 0
        self.playback_after_id = None
        self.playback_path = None

        self.preview_state = {
            "left": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
            "right": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
        }

        self.target_ip = tk.StringVar(value=DEFAULT_TARGET_IP)
        self.target_port = tk.StringVar(value=str(DEFAULT_TARGET_PORT))
        self.device_id = tk.StringVar(value="fsr-device-01")
        self.side = tk.StringVar(value="right")
        self.unit = tk.StringVar(value="newton")
        self._selected_unit = self.unit.get()
        self.preview_unit_label = tk.StringVar(
            value=f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        self.unit.trace_add('write', self._on_unit_change)
        self.rate_hz = tk.StringVar(value=str(DEFAULT_SEND_RATE_HZ))

        self.com_port_1 = tk.StringVar()
        self.com_port_2 = tk.StringVar()
        self.baudrate = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        self.matrix_rows = tk.StringVar(value="12")
        self.matrix_columns = tk.StringVar(value="4")

        self.status = tk.StringVar(value="Sẵn sàng")
        self.summary_left = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.summary_right = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.bt_button_text = tk.StringVar(value="Kết nối 2 FSR")
        self.module_code = tk.StringVar(value="--")
        self.channel_status_1 = tk.StringVar(value="Chưa kết nối")
        self.channel_status_2 = tk.StringVar(value="Chưa kết nối")
        self.log_button_text = tk.StringVar(value="Bắt đầu lưu log")
        self.log_status = tk.StringVar(value="Chưa lưu log")
        self.playback_status = tk.StringVar(value="Chưa mở log")
        self.connection_toggle_text = tk.StringVar(value="▼ Thu gọn thiết lập kết nối")
        self.connection_panel_collapsed = False
        self.connection_settings_body = None
        self.main_notebook = None
        self.total_chart_tab = None

        self._build_ui()
        self.refresh_com_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        connection_section = ttk.Frame(container)
        connection_section.pack(fill=tk.X)
        ttk.Button(
            connection_section,
            textvariable=self.connection_toggle_text,
            command=self._toggle_connection_panel,
        ).pack(fill=tk.X)
        self.connection_settings_body = ttk.Frame(connection_section)
        self.connection_settings_body.pack(fill=tk.X, pady=(6, 0))

        bluetooth = ttk.LabelFrame(
            self.connection_settings_body,
            text="Bluetooth Serial - nhận đồng thời 2 chân",
            padding=10,
        )
        bluetooth.pack(fill=tk.X)

        ttk.Label(bluetooth, text="FSR 1 (tự nhận LL/RR)").grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        self.com_box_1 = ttk.Combobox(
            bluetooth, textvariable=self.com_port_1, width=35, state="readonly"
        )
        self.com_box_1.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.com_box_1.bind("<Button-1>", self._refresh_com_ports_from_event)
        ttk.Label(bluetooth, textvariable=self.channel_status_1, width=22).grid(
            row=0, column=2, padx=(0, 8), sticky="w"
        )

        ttk.Label(bluetooth, text="FSR 2 (tự nhận LL/RR)").grid(
            row=1, column=0, padx=(0, 5), pady=(8, 0), sticky="w"
        )
        self.com_box_2 = ttk.Combobox(
            bluetooth, textvariable=self.com_port_2, width=35, state="readonly"
        )
        self.com_box_2.grid(row=1, column=1, padx=(0, 8), pady=(8, 0), sticky="ew")
        self.com_box_2.bind("<Button-1>", self._refresh_com_ports_from_event)
        ttk.Label(bluetooth, textvariable=self.channel_status_2, width=22).grid(
            row=1, column=2, padx=(0, 8), pady=(8, 0), sticky="w"
        )

        ttk.Button(bluetooth, text="Quét lại", command=self.refresh_com_ports).grid(
            row=0, column=3, padx=(0, 12), sticky="ew"
        )
        ttk.Label(bluetooth, text="Baudrate").grid(row=0, column=4, padx=(0, 5), sticky="w")
        ttk.Combobox(
            bluetooth,
            textvariable=self.baudrate,
            values=("9600", "19200", "38400", "57600", "115200"),
            width=9,
            state="readonly",
        ).grid(row=0, column=5, sticky="w")

        self.bt_button = ttk.Button(
            bluetooth, textvariable=self.bt_button_text, command=self.toggle_stream
        )
        self.bt_button.grid(row=1, column=3, columnspan=3, padx=(0, 0), pady=(8, 0), sticky="ew")

        ttk.Label(bluetooth, text="Kích thước").grid(row=2, column=0, pady=(10, 0), sticky="w")
        dimensions = ttk.Frame(bluetooth)
        dimensions.grid(row=2, column=1, pady=(10, 0), sticky="w")
        ttk.Label(dimensions, text="Hàng").pack(side=tk.LEFT)
        ttk.Entry(dimensions, textvariable=self.matrix_rows, width=6).pack(side=tk.LEFT, padx=(5, 12))
        ttk.Label(dimensions, text="Cột").pack(side=tk.LEFT)
        ttk.Entry(dimensions, textvariable=self.matrix_columns, width=6).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(bluetooth, text="Đã nhận:").grid(
            row=2, column=2, pady=(10, 0), padx=(0, 5), sticky="e"
        )
        ttk.Label(
            bluetooth,
            textvariable=self.module_code,
            font=("Segoe UI", 10, "bold"),
            foreground="#2563eb",
        ).grid(row=2, column=3, columnspan=3, pady=(10, 0), sticky="w")

        bluetooth.columnconfigure(1, weight=1)

        connection = ttk.LabelFrame(
            self.connection_settings_body, text="Đích nhận UDP", padding=10
        )
        connection.pack(fill=tk.X, pady=(10, 0))
        fields = [
            ("IP", self.target_ip, 18),
            ("Port", self.target_port, 8),
            ("Device ID", self.device_id, 18),
            ("Tần số tối đa (Hz)", self.rate_hz, 8),
        ]
        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(connection, text=label).grid(row=0, column=column * 2, padx=(0, 5), sticky="w")
            ttk.Entry(connection, textvariable=variable, width=width).grid(
                row=0, column=column * 2 + 1, padx=(0, 12), sticky="ew"
            )

        ttk.Label(connection, text="Chân (gửi thử)").grid(row=1, column=0, pady=(10, 0), sticky="w")
        ttk.Combobox(
            connection, textvariable=self.side, values=("left", "right"), width=15, state="readonly"
        ).grid(row=1, column=1, pady=(10, 0), sticky="w")
        ttk.Label(connection, text="Đơn vị").grid(row=1, column=2, pady=(10, 0), sticky="w")
        ttk.Combobox(
            connection, textvariable=self.unit, values=("raw_adc", "newton"), width=15, state="readonly"
        ).grid(row=1, column=3, pady=(10, 0), sticky="w")

        ttk.Label(connection, textvariable=self.preview_unit_label).grid(
            row=2, column=2, columnspan=2, pady=(8, 0), sticky='w'
        )

        ttk.Label(connection, textvariable=self.ema_label_text).grid(
            row=1, column=4, pady=(10, 0), padx=(12, 5), sticky='e'
        )
        ttk.Scale(
            connection, from_=0.01, to=1.0, variable=self.ema_alpha,
            command=self._on_alpha_change,
        ).grid(row=1, column=5, columnspan=3, pady=(10, 0), sticky='ew')

        log_controls = ttk.LabelFrame(container, text="Biểu đồ và FSR log", padding=8)
        log_controls.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            log_controls,
            textvariable=self.log_button_text,
            command=self.toggle_logging,
        ).pack(side=tk.LEFT)
        ttk.Button(
            log_controls, text="Mở và chạy log", command=self.open_and_play_log
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_controls, text="Dừng phát", command=self.stop_playback
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_controls, text="Xóa biểu đồ", command=self.clear_charts
        ).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(
            log_controls, text="Xóa file log", command=self.delete_log_file
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(log_controls, textvariable=self.playback_status).pack(side=tk.RIGHT)
        ttk.Label(log_controls, textvariable=self.log_status).pack(side=tk.RIGHT, padx=(0, 18))

        zero_controls = ttk.LabelFrame(container, text='Zero đế / giày · lực tăng so với nền', padding=6)
        zero_controls.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(zero_controls, textvariable=self.zero_button_text,
                   command=self._toggle_zero).pack(side=tk.LEFT)
        self.zero_left_button = ttk.Button(zero_controls, text='Zero chân trái',
                                          command=lambda: self._start_zero(('left',)))
        self.zero_left_button.pack(side=tk.LEFT, padx=(8, 0))
        self.zero_right_button = ttk.Button(zero_controls, text='Zero chân phải',
                                           command=lambda: self._start_zero(('right',)))
        self.zero_right_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(zero_controls, textvariable=self.zero_status, wraplength=560).pack(side=tk.LEFT, padx=12)

        fsi_controls = ttk.LabelFrame(
            container,
            text="FSI theo pha · vùng cố định trên 48 ô",
            padding=6,
        )
        fsi_controls.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(
            fsi_controls,
            text="Gót: 42,43,46,47 · Mũi: 6,7,8,10,11,12,14,15,16 · 100% = cân bằng",
        ).pack(anchor="w")
        ttk.Button(
            fsi_controls,
            textvariable=self.fsi_register_text,
            command=self._toggle_fsi_registration,
        ).pack(anchor="w", pady=(3, 2))
        ttk.Label(fsi_controls, textvariable=self.fsi_status).pack(anchor="w", pady=(2, 4))
        fsi_body = ttk.Frame(fsi_controls)
        fsi_body.pack(fill=tk.X)
        fsi_columns = ("pair", "phase", "region", "left", "right", "fsi", "quality")
        self.fsi_tree = ttk.Treeview(fsi_body, columns=fsi_columns, show="headings", height=5)
        fsi_headers = {
            "pair": "Cặp bước", "phase": "Pha", "region": "Vùng",
            "left": "Trái", "right": "Phải", "fsi": "FSI %", "quality": "Chất lượng",
        }
        for column in fsi_columns:
            self.fsi_tree.heading(column, text=fsi_headers[column])
            self.fsi_tree.column(column, width=92 if column not in ("phase", "region") else 140, anchor="center")
        self.fsi_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.fsi_summary_tree = ttk.Treeview(
            fsi_body,
            columns=("phase", "region", "mean", "median", "count"),
            show="headings",
            height=5,
        )
        for column, title in (("phase", "Pha"), ("region", "Vùng"), ("mean", "TB"), ("median", "Trung vị"), ("count", "n")):
            self.fsi_summary_tree.heading(column, text=title)
            self.fsi_summary_tree.column(column, width=88 if column != "phase" else 115, anchor="center")
        self.fsi_summary_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self.fsi_trend_canvas = tk.Canvas(
            fsi_controls, height=115, background="#ffffff",
            highlightthickness=1, highlightbackground="#cbd5e1",
        )
        self.fsi_trend_canvas.pack(fill=tk.X, pady=(6, 0))

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True, pady=12)
        self.main_notebook = notebook

        map_tab = ttk.Frame(notebook)
        total_chart_tab = ttk.Frame(notebook, padding=8)
        region_chart_tab = ttk.Frame(notebook, padding=8)
        self.total_chart_tab = total_chart_tab
        notebook.add(map_tab, text="Bản đồ lực")
        notebook.add(total_chart_tab, text="Tổng tải")
        notebook.add(region_chart_tab, text="Ba vùng bàn chân")

        body = ttk.Frame(map_tab)
        body.pack(fill=tk.BOTH, expand=True, pady=12)

        editor_frame = ttk.LabelFrame(body, text="Ma trận FSR dạng JSON (gửi thử)", padding=10)
        editor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 6))
        self.matrix_text = tk.Text(editor_frame, width=31, wrap=tk.NONE, font=("Consolas", 11))
        self.matrix_text.pack(fill=tk.BOTH, expand=True)
        sample_12x4 = "[\n" + ",\n".join(["  [0, 0, 0, 0]"] * 12) + "\n]"
        self.matrix_text.insert("1.0", sample_12x4)

        preview_frame = ttk.LabelFrame(
            body, text="Xem trước lực từng điểm - 2 chân", padding=8
        )
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        left_preview = ttk.LabelFrame(preview_frame, text="CHÂN TRÁI (LL)", padding=5)
        left_preview.grid(row=0, column=0, padx=(0, 4), sticky="nsew")
        self.canvas_left = tk.Canvas(
            left_preview, background="#111827", highlightthickness=0
        )
        self.canvas_left.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            left_preview, textvariable=self.summary_left, anchor="w", justify=tk.LEFT
        ).pack(fill=tk.X, pady=(6, 0))

        right_preview = ttk.LabelFrame(preview_frame, text="CHÂN PHẢI (RR)", padding=5)
        right_preview.grid(row=0, column=1, padx=(4, 0), sticky="nsew")
        self.canvas_right = tk.Canvas(
            right_preview, background="#111827", highlightthickness=0
        )
        self.canvas_right.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            right_preview, textvariable=self.summary_right, anchor="w", justify=tk.LEFT
        ).pack(fill=tk.X, pady=(6, 0))

        self.total_chart_canvas = tk.Canvas(
            total_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.total_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.total_chart_canvas.bind("<Configure>", self._on_chart_resize)

        self.region_chart_canvas = tk.Canvas(
            region_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.region_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.region_chart_canvas.bind("<Configure>", self._on_chart_resize)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Xem ma trận", command=self.preview_manual_matrix).pack(side=tk.LEFT)
        ttk.Button(controls, text="Gửi 1 frame", command=self.send_manual_once).pack(side=tk.LEFT, padx=8)
        ttk.Label(controls, textvariable=self.status).pack(side=tk.RIGHT)
        empty_matrix = [[0.0] * 4 for _ in range(12)]
        self.root.after(80, self.draw_matrix, empty_matrix, "left")
        self.root.after(80, self.draw_matrix, empty_matrix, "right")
        self.root.after(120, self._redraw_charts)

    def _toggle_connection_panel(self):
        self._set_connection_panel_collapsed(not self.connection_panel_collapsed)

    def _set_connection_panel_collapsed(self, collapsed):
        if self.connection_settings_body is None:
            return
        self.connection_panel_collapsed = bool(collapsed)
        if self.connection_panel_collapsed:
            self.connection_settings_body.pack_forget()
            self.connection_toggle_text.set("▶ Hiện thiết lập kết nối")
        else:
            if not self.connection_settings_body.winfo_manager():
                self.connection_settings_body.pack(fill=tk.X, pady=(6, 0))
            self.connection_toggle_text.set("▼ Thu gọn thiết lập kết nối")
        self.root.after_idle(self._schedule_chart_redraw)

    def _refresh_zero_controls(self):
        sides, pending = self.shoe_zero.state()
        self.zero_button_text.set('Huỷ zero' if sides or pending else 'Zero hết')
        for button in (self.zero_left_button, self.zero_right_button):
            button.configure(state='disabled' if pending else 'normal')

    def _reset_zero(self, reason='Đã huỷ zero · trở về lực trước zero'):
        sides, pending = self.shoe_zero.state()
        if self.zero_after_id is not None:
            self.root.after_cancel(self.zero_after_id)
            self.zero_after_id = None
        self.shoe_zero.reset()
        if sides or pending:
            self.clear_charts()
        self.zero_status.set(reason)
        self._refresh_zero_controls()

    def _toggle_zero(self):
        sides, pending = self.shoe_zero.state()
        if sides or pending:
            self._reset_zero()
            self.clear_charts()
            # Restore the current display without waiting for a new frame.
            for side, raw in list(self.last_raw_matrices.items()):
                self.draw_matrix(matrix_for_unit(raw, self._selected_unit, side),
                                 side, self._selected_unit)
        else:
            self._start_zero(('left', 'right'))

    def _start_zero(self, sides):
        if not self.running or self._selected_unit != 'newton':
            messagebox.showwarning('Lấy zero', 'Kết nối FSR trực tiếp và chọn Newton trước khi lấy zero.')
            return
        label = 'cả hai chân' if len(sides) == 2 else ('chân trái' if sides[0] == 'left' else 'chân phải')
        if not messagebox.askokcancel('Lấy zero khi mang giày',
                f'Ngồi vững, nhấc {label} khỏi sàn và giữ yên.\n'
                'Không đứng chịu tải khi bấm zero. Phần mềm không tự nhận biết chân đang chịu tải.\n'
                'Bấm OK khi đã sẵn sàng; thu mẫu khoảng 3 giây.', parent=self.root):
            return
        try:
            self.zero_started_at = time.monotonic()
            self.shoe_zero.start(sides, self.zero_started_at)
        except ValueError as exc:
            self.zero_status.set(str(exc))
            return
        self._refresh_zero_controls()
        self._poll_zero()

    def _poll_zero(self):
        self.zero_after_id = None
        if not self.shoe_zero.state()[1]:
            return
        now = time.monotonic()
        remaining = self.shoe_zero.duration-(now-self.zero_started_at)
        if remaining > 0:
            self.zero_status.set(f'Đang lấy zero: còn {remaining:.1f}s · giữ chân khỏi sàn')
            self.zero_after_id = self.root.after(100, self._poll_zero)
            return
        try:
            self.shoe_zero.finish(now)
            sides, _ = self.shoe_zero.state()
            labels = ', '.join('trái' if s == 'left' else 'phải' for s in sides)
            self.zero_status.set(f'Đã zero: {labels} · đang hiển thị lực tăng thêm')
            self.clear_charts()
        except ValueError as exc:
            retained = ' · Zero cũ vẫn giữ' if self.shoe_zero.state()[0] else ''
            self.zero_status.set(f'Không lấy được zero: {exc}{retained}')
        self._refresh_zero_controls()

    def _on_unit_change(self, *_args):
        self._reset_zero('Đổi đơn vị: zero đã huỷ')
        selected = self.unit.get().strip().lower()
        self._selected_unit = selected if selected in ('raw_adc', 'newton') else 'raw_adc'
        self.clear_charts()
        self.preview_unit_label.set(
            f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        for side, raw_matrix in list(self.last_raw_matrices.items()):
            self.draw_matrix(
                matrix_for_unit(raw_matrix, self._selected_unit, side),
                side,
                self._selected_unit,
            )
            self._append_chart_sample(
                side,
                matrix_for_unit(raw_matrix, self._selected_unit, side),
                unit=self._selected_unit,
            )
        if self.last_raw_matrices:
            self.status.set(f'Đã đổi sang {unit_label(self._selected_unit)}')

    def _on_alpha_change(self, value):
        if hasattr(self, 'zero_left_button'):
            self._reset_zero('Đổi bộ lọc: cần lấy zero lại')
        self.ema_alpha_value = min(max(float(value), 0.01), 1.0)
        self.ema_label_text.set(f'EMA alpha: {self.ema_alpha_value:.2f}')

    def _apply_ema_filter(self, channel_id, matrix):
        matrix = validate_matrix(matrix)
        if any(not math.isfinite(v) for row in matrix for v in row):
            raise ValueError('ADC không hữu hạn; bỏ frame, giữ nguyên bộ lọc.')
        previous = self.smoothed_matrices.get(channel_id)
        if (
            previous is None
            or len(previous) != len(matrix)
            or len(previous[0]) != len(matrix[0])
        ):
            filtered = [row[:] for row in matrix]
        else:
            alpha = self.ema_alpha_value
            filtered = [
                [
                    alpha * value
                    + (1.0 - alpha) * previous[row_index][column_index]
                    for column_index, value in enumerate(row)
                ]
                for row_index, row in enumerate(matrix)
            ]
        self.smoothed_matrices[channel_id] = filtered
        return [row[:] for row in filtered]

    @staticmethod
    def _chart_unit_label(unit):
        return "N" if str(unit).lower() == "newton" else "ADC"

    def _append_chart_sample(self, side, matrix, sample_time=None, unit=None):
        if side not in self.chart_history:
            return
        matrix = validate_matrix(matrix)
        unit = str(unit or self._selected_unit).lower()
        if self.chart_unit is not None and self.chart_unit != unit:
            for history in self.chart_history.values():
                history.clear()
            self.chart_started_at = time.monotonic()
        self.chart_unit = unit
        regions = matrix_region_totals(matrix)
        timestamp = (
            float(sample_time)
            if sample_time is not None
            else time.monotonic() - self.chart_started_at
        )
        self.chart_history[side].append(
            {
                "time": max(0.0, timestamp),
                "total": regions["total"],
                "heel": regions["heel"],
                "midfoot": regions["midfoot"],
                "forefoot": regions["forefoot"],
            }
        )
        self._schedule_chart_redraw()

    def _reset_fsi(self):
        if self.fsi_analyzer is not None:
            self.fsi_analyzer.reset()
        self.fsi_last_refresh = 0.0
        if self.fsi_tree is not None:
            for item in self.fsi_tree.get_children():
                self.fsi_tree.delete(item)
        if self.fsi_summary_tree is not None:
            for item in self.fsi_summary_tree.get_children():
                self.fsi_summary_tree.delete(item)
        self.fsi_status.set("FSI: đang chờ đủ cặp bước")

    def _toggle_fsi_registration(self):
        self.fsi_roi_registered = not self.fsi_roi_registered
        self._reset_fsi()
        if self.fsi_roi_registered:
            self.fsi_register_text.set("ROI đã đăng ký hai chân · bấm để huỷ")
            self.fsi_status.set("FSI: đã đăng ký ROI; đang chờ cặp bước")
        else:
            self.fsi_register_text.set("Đăng ký ROI sau khi căn dấu chân")
            self.fsi_status.set("FSI: chưa đăng ký ROI hai chân")

    def _append_fsi_sample(self, side, matrix, unit, sample_time=None):
        """Store all 48 cells; only calibrated Newton samples can form FSI."""
        if self.fsi_analyzer is None:
            return
        timestamp = float(sample_time) if sample_time is not None else time.monotonic()
        is_force = str(unit).strip().lower() == "newton"
        self.fsi_analyzer.add_sample(
            side,
            timestamp,
            matrix,
            unit=unit,
            valid=is_force and self.fsi_roi_registered,
            quality=("valid" if is_force and self.fsi_roi_registered
                     else "roi_not_registered" if is_force else "unit_not_force"),
        )
        if timestamp - self.fsi_last_refresh < 0.25:
            return
        self.fsi_last_refresh = timestamp
        self._refresh_fsi_view()

    def _refresh_fsi_view(self):
        if self.fsi_analyzer is None or self.fsi_tree is None:
            return
        snapshot = self.fsi_analyzer.snapshot()
        for item in self.fsi_tree.get_children():
            self.fsi_tree.delete(item)
        for row in snapshot["pairs"][-12:]:
            phase_label = {
                "contact": "Tiếp đất gót",
                "midstance": "Pha giữa",
                "push": "Tải mũi cuối stance",
            }.get(row["phase"], row["phase"])
            region_label = {
                "heel": "Gót",
                "forefoot": "Mũi",
                "stance_sampled": "Gót–mũi mẫu",
            }.get(row["region"], row["region"])
            values = [
                row["pair_id"], phase_label, region_label,
                "--" if row["left_value"] is None else f'{row["left_value"]:.2f}',
                "--" if row["right_value"] is None else f'{row["right_value"]:.2f}',
                "--" if row["fsi"] is None else f'{row["fsi"]:.2f}',
                row["quality"],
            ]
            self.fsi_tree.insert("", tk.END, values=values)
        if self.fsi_summary_tree is not None:
            for item in self.fsi_summary_tree.get_children():
                self.fsi_summary_tree.delete(item)
            for row in snapshot["summary"]:
                self.fsi_summary_tree.insert(
                    "", tk.END,
                    values=(row["phase"], row["region"], row["fsi_mean"], row["fsi_median"], row["valid_pair_count"]),
                )
        self._draw_fsi_trend(snapshot["pairs"])
        pair_count = len({row["pair_id"] for row in snapshot["pairs"]})
        valid_count = sum(row["quality"] == "valid" for row in snapshot["pairs"])
        if not self.fsi_roi_registered:
            self.fsi_status.set("FSI: chưa đăng ký ROI hai chân · toàn bộ 48 ô chưa dùng để tính FSI")
        else:
            self.fsi_status.set(
                f"FSI: {pair_count} cặp bước · {valid_count} dòng hợp lệ · toàn bộ 48 ô dùng để bắt tiếp xúc"
            )

    def _draw_fsi_trend(self, rows):
        if self.fsi_trend_canvas is None:
            return
        canvas = self.fsi_trend_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 115)
        left, right, top, bottom = 42, 18, 18, 24
        x0, x1, y0, y1 = left, width - right, top, height - bottom
        canvas.create_text(left, 8, text="FSI theo cặp bước", anchor="w", fill="#334155", font=("Segoe UI", 9, "bold"))
        for tick in (0, 50, 100):
            y = y1 - tick / 100 * (y1 - y0)
            canvas.create_line(x0, y, x1, y, fill="#e2e8f0")
            canvas.create_text(x0 - 5, y, text=str(tick), anchor="e", fill="#64748b", font=("Segoe UI", 8))
        groups = {
            ("contact", "heel"): ("Tiếp đất gót", "#2563eb"),
            ("midstance", "heel"): ("Giữa gót", "#0f766e"),
            ("midstance", "forefoot"): ("Giữa mũi", "#ea6a14"),
            ("push", "forefoot"): ("Tải mũi", "#7c3aed"),
        }
        pair_ids = []
        for row in rows:
            if row.get("pair_id") not in pair_ids:
                pair_ids.append(row.get("pair_id"))
        if not pair_ids:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Chưa đủ cặp bước", fill="#64748b")
            return
        x_step = (x1 - x0) / max(1, len(pair_ids) - 1)
        for (phase, region), (label, color) in groups.items():
            by_pair = {(row.get("pair_id")): row.get("fsi") for row in rows
                       if row.get("phase") == phase and row.get("region") == region}
            points = []
            for index, pair_id in enumerate(pair_ids):
                value = by_pair.get(pair_id)
                if value is None:
                    continue
                points.extend((x0 + index * x_step, y1 - float(value) / 100 * (y1 - y0)))
            if len(points) >= 2:
                canvas.create_line(*points, fill=color, width=2)
            if points:
                canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=color, outline=color)
            legend_x = x0 + 8 + list(groups).index((phase, region)) * 112
            canvas.create_line(legend_x, height - 10, legend_x + 14, height - 10, fill=color, width=2)
            canvas.create_text(legend_x + 18, height - 10, text=label, anchor="w", fill="#475569", font=("Segoe UI", 8))

    def _on_chart_resize(self, _event=None):
        self._schedule_chart_redraw()

    def _schedule_chart_redraw(self):
        if self.chart_redraw_pending:
            return
        self.chart_redraw_pending = True
        self.root.after(80, self._redraw_charts)

    def _redraw_charts(self):
        self.chart_redraw_pending = False
        if self.total_chart_canvas is not None:
            self._draw_total_chart()
        if self.region_chart_canvas is not None:
            self._draw_region_chart()

    @staticmethod
    def _visible_history(history, x_start, x_end):
        return [point for point in history if x_start <= point["time"] <= x_end]

    @staticmethod
    def _draw_chart_line(canvas, points, x_map, y_map, color, dash=None):
        segment = []
        previous_time = None
        for point in points:
            timestamp, value = point
            if previous_time is not None and timestamp - previous_time > 0.6:
                if len(segment) >= 4:
                    canvas.create_line(
                        *segment, fill=color, width=2.5, dash=dash, smooth=False
                    )
                segment = []
            segment.extend((x_map(timestamp), y_map(value)))
            previous_time = timestamp
        if len(segment) >= 4:
            canvas.create_line(
                *segment, fill=color, width=2.5, dash=dash, smooth=False
            )

    def _draw_chart_frame(self, canvas, title, series, legend, minimum_y):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 260)
        left, right, top, bottom = 76, 24, 82, 58
        plot_left, plot_top = left, top
        plot_right, plot_bottom = width - right, height - bottom

        canvas.create_text(
            width / 2, 23, text=title, fill="#172033", font=("Segoe UI", 14, "bold")
        )

        all_times = [
            point["time"]
            for side in ("left", "right")
            for point in self.chart_history[side]
        ]
        latest_time = max(all_times, default=0.0)
        x_end = max(CHART_WINDOW_SECONDS, latest_time)
        x_start = max(0.0, x_end - CHART_WINDOW_SECONDS)

        visible_by_side = {
            side: self._visible_history(self.chart_history[side], x_start, x_end)
            for side in ("left", "right")
        }
        visible_values = []
        for item in series:
            for point in visible_by_side[item["side"]]:
                visible_values.append(point[item["field"]])
        y_max = nice_axis_max(max(visible_values, default=0.0), minimum_y)

        def x_map(value):
            span = max(x_end - x_start, 1e-6)
            return plot_left + (value - x_start) / span * (plot_right - plot_left)

        def y_map(value):
            return plot_bottom - max(0.0, value) / y_max * (plot_bottom - plot_top)

        for index in range(6):
            fraction = index / 5
            x = plot_left + fraction * (plot_right - plot_left)
            y = plot_bottom - fraction * (plot_bottom - plot_top)
            canvas.create_line(x, plot_top, x, plot_bottom, fill="#e2e8f0")
            canvas.create_line(plot_left, y, plot_right, y, fill="#e2e8f0")
            canvas.create_text(
                x,
                plot_bottom + 20,
                text=f"{x_start + fraction * (x_end - x_start):.0f}",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )
            canvas.create_text(
                plot_left - 12,
                y,
                text=f"{fraction * y_max:.0f}",
                anchor="e",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )

        canvas.create_rectangle(
            plot_left, plot_top, plot_right, plot_bottom, outline="#9eacbb", width=1
        )
        canvas.create_text(
            (plot_left + plot_right) / 2,
            height - 18,
            text="Thời gian (s)",
            fill="#334155",
            font=("Segoe UI", 10),
        )
        canvas.create_text(
            19,
            (plot_top + plot_bottom) / 2,
            text=f"Lực ({self._chart_unit_label(self.chart_unit)})",
            angle=90,
            fill="#334155",
            font=("Segoe UI", 10),
        )

        legend_x = plot_left
        legend_y = 52
        for label, color, dash in legend:
            canvas.create_line(
                legend_x, legend_y, legend_x + 28, legend_y,
                fill=color, width=3, dash=dash,
            )
            canvas.create_text(
                legend_x + 35,
                legend_y,
                text=label,
                anchor="w",
                fill="#334155",
                font=("Segoe UI", 9),
            )
            label_width = max(54, len(label) * 7)
            legend_x += 48 + label_width

        for item in series:
            points = [
                (point["time"], point[item["field"]])
                for point in visible_by_side[item["side"]]
            ]
            self._draw_chart_line(
                canvas,
                points,
                x_map,
                y_map,
                item["color"],
                item.get("dash"),
            )

        if not visible_values:
            canvas.create_text(
                (plot_left + plot_right) / 2,
                (plot_top + plot_bottom) / 2,
                text="Chưa có dữ liệu FSR",
                fill="#64748b",
                font=("Segoe UI", 12),
            )

    def _draw_total_chart(self):
        self._draw_chart_frame(
            self.total_chart_canvas,
            "TỔNG TẢI TRÊN TỪNG CHÂN",
            [
                {"side": "left", "field": "total", "color": CHART_COLORS["left"]},
                {
                    "side": "right",
                    "field": "total",
                    "color": CHART_COLORS["right"],
                    "dash": (8, 4),
                },
            ],
            [
                ("Chân trái", CHART_COLORS["left"], None),
                ("Chân phải", CHART_COLORS["right"], (8, 4)),
            ],
            100.0 if self.chart_unit == "newton" else 1000.0,
        )

    def _draw_region_chart(self):
        series = []
        for side, dash in (("left", None), ("right", (8, 4))):
            for field in ("heel", "midfoot", "forefoot"):
                series.append(
                    {
                        "side": side,
                        "field": field,
                        "color": CHART_COLORS[field],
                        "dash": dash,
                    }
                )
        self._draw_chart_frame(
            self.region_chart_canvas,
            "PHÂN BỐ LỰC THEO BA VÙNG BÀN CHÂN",
            series,
            [
                ("Gót", CHART_COLORS["heel"], None),
                ("Giữa", CHART_COLORS["midfoot"], None),
                ("Mũi", CHART_COLORS["forefoot"], None),
                ("Trái: liền", "#475569", None),
                ("Phải: đứt", "#475569", (8, 4)),
            ],
            50.0 if self.chart_unit == "newton" else 500.0,
        )

    def clear_charts(self):
        for history in self.chart_history.values():
            history.clear()
        self._reset_fsi()
        self.chart_started_at = time.monotonic()
        self.chart_unit = self._selected_unit
        self._schedule_chart_redraw()
        self.status.set("Đã xóa dữ liệu đang vẽ trên biểu đồ")

    def _default_log_directory(self):
        directory = Path(__file__).resolve().parent / "fsr_logs"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def toggle_logging(self):
        if self.log_handle is not None:
            self._stop_logging()
            return

        directory = self._default_log_directory()
        default_name = time.strftime("fsr_%Y%m%d_%H%M%S.jsonl")
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Lưu FSR log",
            initialdir=str(directory),
            initialfile=default_name,
            defaultextension=".jsonl",
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
            confirmoverwrite=True,
        )
        if not selected:
            return

        try:
            handle = open(selected, "w", encoding="utf-8", buffering=1)
            header = {
                "type": "fsr_log",
                "version": 1,
                "created_at": time.time(),
                "description": "Raw ADC, EMA ADC and displayed FSR matrix",
            }
            handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        except OSError as exc:
            messagebox.showerror("Không lưu được log", str(exc))
            return

        with self.log_lock:
            self.log_handle = handle
            self.log_path = Path(selected).resolve()
            self.log_started_at = time.monotonic()
            self.log_sample_count = 0
        self.log_button_text.set("Dừng và đóng log")
        self.log_status.set(f"Đang lưu: {Path(selected).name}")

    def _stop_logging(self, status_text=None):
        with self.log_lock:
            handle = self.log_handle
            path = self.log_path
            count = self.log_sample_count
            self.log_handle = None
            self.log_started_at = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
        self.log_button_text.set("Bắt đầu lưu log")
        if status_text is not None:
            self.log_status.set(status_text)
        elif path is not None:
            self.log_status.set(f"Đã lưu {count} mẫu: {path.name}")
        else:
            self.log_status.set("Chưa lưu log")

    def _write_log_sample(
        self,
        side,
        raw_matrix,
        filtered_raw_matrix,
        display_matrix,
        unit,
        received_monotonic,
        zero_metadata=None,
    ):
        with self.log_lock:
            handle = self.log_handle
            started_at = self.log_started_at
            if handle is None or started_at is None:
                return
            record = {
                "type": "fsr_sample",
                "elapsed": max(0.0, received_monotonic - started_at),
                "received_at": time.time(),
                "side": side,
                "unit": unit,
                "rows": len(display_matrix),
                "columns": len(display_matrix[0]),
                "raw_values": raw_matrix,
                "filtered_raw_values": filtered_raw_matrix,
                "values": display_matrix,
                **calibration_metadata(side, unit),
                **(zero_metadata or {'zero_applied': False, 'zero_collecting': False}),
            }
            try:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.log_sample_count += 1
                count = self.log_sample_count
                if count % 20 == 0:
                    handle.flush()
                    self.root.after(
                        0,
                        self.log_status.set,
                        f"Đang lưu: {self.log_path.name} · {count} mẫu",
                    )
            except OSError as exc:
                self.log_handle = None
                self.log_started_at = None
                try:
                    handle.close()
                except OSError:
                    pass
                self.root.after(0, self._log_failed, str(exc))

    def _log_failed(self, error_message):
        self.log_button_text.set("Bắt đầu lưu log")
        self.log_status.set("Lỗi ghi log")
        messagebox.showerror("Lỗi ghi FSR log", error_message)

    def open_and_play_log(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Mở FSR log",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return

        records = []
        try:
            with open(selected, "r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Dòng {line_number}: JSON không hợp lệ") from exc
                    if record.get("type") == "fsr_log":
                        continue
                    side = str(record.get("side", "")).lower()
                    if side not in ("left", "right"):
                        continue
                    matrix = record.get("values")
                    unit = str(record.get("unit", "raw_adc")).lower()
                    if record.get("forceValues") and unit.lower().startswith("n"):
                        matrix = record["forceValues"]
                        unit = "newton"
                    matrix = validate_matrix(matrix)
                    elapsed = float(record.get("elapsed", record.get("time", 0.0)))
                    records.append(
                        {
                            "elapsed": max(0.0, elapsed),
                            "side": side,
                            "unit": "newton" if unit in ("n", "n_estimated") else unit,
                            "values": matrix,
                            "raw_values": record.get("raw_values", record.get("rawAdcValues")),
                        }
                    )
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Không mở được FSR log", str(exc))
            return

        if not records:
            messagebox.showwarning("FSR log trống", "Không tìm thấy mẫu FSR hợp lệ trong file.")
            return

        records.sort(key=lambda item: item["elapsed"])
        if self.running:
            self._stop_stream("Đã ngắt FSR thật để chạy log")
        self._stop_logging()
        self.stop_playback(silent=True)
        self.clear_charts()
        self.playback_records = records
        self.playback_index = 0
        self.playback_path = Path(selected).resolve()
        self.chart_unit = records[0]["unit"]
        self.playback_status.set(f"Đang chạy: {self.playback_path.name}")
        self._playback_step()

    def _playback_step(self):
        self.playback_after_id = None
        if self.playback_index >= len(self.playback_records):
            name = self.playback_path.name if self.playback_path else "log"
            self.playback_status.set(f"Đã chạy xong: {name}")
            return

        record = self.playback_records[self.playback_index]
        matrix = record["values"]
        side = record["side"]
        unit = record["unit"]
        raw_values = record.get("raw_values")
        if isinstance(raw_values, list):
            try:
                self.last_raw_matrices[side] = validate_matrix(raw_values)
            except ValueError:
                pass
        self.draw_matrix(matrix, side, unit)
        self._append_chart_sample(side, matrix, record["elapsed"], unit)
        self._append_fsi_sample(side, matrix, unit, record["elapsed"])
        self.playback_index += 1

        if self.playback_index < len(self.playback_records):
            next_record = self.playback_records[self.playback_index]
            delay_seconds = max(0.0, next_record["elapsed"] - record["elapsed"])
            delay_ms = max(1, min(2000, round(delay_seconds * 1000)))
            self.playback_after_id = self.root.after(delay_ms, self._playback_step)
        else:
            self.playback_status.set(f"Đã chạy xong: {self.playback_path.name}")

    def stop_playback(self, silent=False):
        if self.playback_after_id is not None:
            try:
                self.root.after_cancel(self.playback_after_id)
            except tk.TclError:
                pass
        was_running = self.playback_after_id is not None
        self.playback_after_id = None
        self.playback_records = []
        self.playback_index = 0
        if not silent:
            self.playback_status.set("Đã dừng phát log" if was_running else "Chưa chạy log")

    def delete_log_file(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Chọn FSR log cần xóa",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return
        path = Path(selected).resolve()
        if not messagebox.askyesno(
            "Xóa FSR log",
            f"Xóa vĩnh viễn file này?\n\n{path}",
            parent=self.root,
        ):
            return

        if self.log_path == path and self.log_handle is not None:
            self._stop_logging("Đã đóng log trước khi xóa")
        if self.playback_path == path:
            self.stop_playback(silent=True)
        try:
            path.unlink()
        except OSError as exc:
            messagebox.showerror("Không xóa được log", str(exc))
            return
        self.log_status.set(f"Đã xóa: {path.name}")
        self.playback_status.set("Chưa mở log")

    def refresh_com_ports(self):
        boxes = (self.com_box_1, self.com_box_2)
        variables = (self.com_port_1, self.com_port_2)
        if list_ports is None:
            for box in boxes:
                box["values"] = ()
            for variable in variables:
                variable.set("")
            self.status.set("Thiếu pyserial – chạy: py -m pip install pyserial")
            return

        current_devices = [
            self._selected_com_device(variable, allow_empty=True)
            for variable in variables
        ]
        all_ports = list(list_ports.comports())
        ports = sorted(
            selectable_fsr_ports(all_ports),
            key=lambda port: self._com_sort_key(port.device),
        )
        display_values = [
            f"{port.device} - {port.description or 'Serial device'}"
            for port in ports
        ]
        for box in boxes:
            box["values"] = display_values

        if not display_values:
            self.status.set("Không quét thấy cổng COM")
            return

        by_device = {item.split(" - ", 1)[0]: item for item in display_values}
        preferred_devices = [port.device for port in ports]

        selected = []
        for current in current_devices:
            if current in by_device and current not in selected:
                selected.append(current)
            else:
                selected.append("")

        for index in range(2):
            if selected[index]:
                continue
            candidate = next(
                (device for device in preferred_devices if device not in selected),
                None,
            )
            if candidate:
                selected[index] = candidate

        for variable, device in zip(variables, selected):
            variable.set(by_device.get(device, device))

        chosen = ", ".join(device for device in selected if device) or "chưa chọn"
        ignored = max(0, len(all_ports) - len(ports))
        ignored_text = f"; bỏ qua {ignored} cổng Bluetooth chiều vào" if ignored else ""
        self.status.set(
            f"Tìm thấy {len(display_values)} cổng FSR chiều ra; tự chọn {chosen}{ignored_text}"
        )

    def _refresh_com_ports_from_event(self, _event=None):
        if not self.running:
            self.refresh_com_ports()

    @staticmethod
    def _com_sort_key(device):
        match = re.fullmatch(r"COM(\d+)", device.strip(), flags=re.IGNORECASE)
        return (0, int(match.group(1))) if match else (1, device.casefold())

    def _selected_com_device(self, variable, allow_empty=False):
        value = variable.get().strip()
        if not value:
            if allow_empty:
                return ""
            raise ValueError("Chưa chọn cổng COM")
        return value.split(" - ", 1)[0].strip()

    def _serial_settings(self):
        if serial is None:
            raise ValueError("Chưa cài pyserial")

        devices = [
            self._selected_com_device(self.com_port_1, allow_empty=True),
            self._selected_com_device(self.com_port_2, allow_empty=True),
        ]
        if not any(devices):
            raise ValueError("Chưa chọn cổng COM cho FSR")
        if devices[0] and devices[0] == devices[1]:
            raise ValueError("FSR 1 và FSR 2 đang chọn cùng một cổng COM")

        available = {
            str(getattr(port, "device", ""))
            for port in selectable_fsr_ports(list_ports.comports())
        }
        missing = [device for device in devices if device and device not in available]
        if missing:
            raise ValueError(
                "Cổng không còn sẵn sàng hoặc là cổng Bluetooth chiều vào: "
                + ", ".join(missing)
                + ". Hãy bấm Quét lại."
            )

        baudrate = int(self.baudrate.get())
        if baudrate <= 0:
            raise ValueError("Baudrate phải lớn hơn 0")

        rows_text = self.matrix_rows.get().strip()
        columns_text = self.matrix_columns.get().strip()
        rows = int(rows_text) if rows_text else None
        columns = int(columns_text) if columns_text else None
        if (rows is None) != (columns is None):
            raise ValueError("Phải nhập cả số hàng và số cột")
        if rows is not None and (rows <= 0 or columns <= 0):
            raise ValueError("Số hàng và số cột phải lớn hơn 0")

        settings = []
        fallback_sides = ("left", "right")
        for channel_id, (device, fallback_side) in enumerate(
            zip(devices, fallback_sides), start=1
        ):
            if device:
                settings.append(
                    (channel_id, device, baudrate, rows, columns, fallback_side)
                )
        return settings

    def _connection_settings(self):
        ip = self.target_ip.get().strip()
        if not ip:
            raise ValueError("IP đích không được rỗng")
        port = int(self.target_port.get())
        if not 1 <= port <= 65535:
            raise ValueError("Port không hợp lệ")
        rate = float(self.rate_hz.get())
        if rate <= 0 or rate > 200:
            raise ValueError("Tần số không hợp lệ")
        return ip, port, rate

    def _packet_settings(self):
        return (
            self.device_id.get().strip() or "fsr-device-01",
            self.side.get(),
            self._selected_unit,
        )

    def _manual_matrix(self):
        try:
            return validate_matrix(json.loads(self.matrix_text.get("1.0", tk.END)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc.msg}") from exc

    def preview_manual_matrix(self):
        if self.running:
            messagebox.showwarning('Gửi thử', 'Ngắt FSR trực tiếp trước khi thử ma trận thủ công.')
            return
        try:
            side = self.side.get()
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit, side)
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(
                matrix,
                side,
                self._selected_unit,
            )
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
            self._append_fsi_sample(side, matrix, self._selected_unit)
        except ValueError as exc:
            messagebox.showerror("Lỗi", str(exc))

    def send_manual_once(self):
        if self.running:
            messagebox.showwarning('Gửi thử', 'Ngắt FSR trực tiếp trước khi thử ma trận thủ công.')
            return
        try:
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit, self.side.get())
            ip, port, _ = self._connection_settings()
            packet_settings = self._packet_settings()
            status = self._send_matrix_udp(matrix, ip, port, packet_settings)
            self.status.set(status)
            side = self.side.get()
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(matrix, side, self._selected_unit)
            now = time.monotonic()
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
            self._append_fsi_sample(side, matrix, self._selected_unit, now)
            self._write_log_sample(
                side,
                raw_matrix,
                raw_matrix,
                matrix,
                self._selected_unit,
                now,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))

    def _convert_live_matrix(self, raw_matrix, unit, side, now):
        raw_matrix = validate_matrix(raw_matrix)
        if any(not math.isfinite(v) for row in raw_matrix for v in row):
            raise ValueError('ADC không hữu hạn; không thể tính lực/zero.')
        matrix = matrix_for_unit(raw_matrix, unit, side)
        if unit == 'newton':
            return self.shoe_zero.process(side, matrix, now)
        return matrix, {'zero_applied': False, 'zero_collecting': False}

    def _send_matrix_udp(self, matrix, ip, port, packet_settings, zero_metadata=None):
        matrix = validate_matrix(matrix)
        device_id, side, unit = packet_settings
        with self.send_lock:
            packet = build_packet(device_id, side, unit, self.sequence, matrix)
            packet.update(zero_metadata or {'zero_applied': False, 'zero_collecting': False})
            encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
            if len(encoded) > 60000:
                raise ValueError("Gói tin quá lớn")
            self.socket.sendto(encoded, (ip, port))
            self.sequence += 1
        return f"{side.upper()} frame #{packet['sequence']} -> {ip}:{port}"

    def toggle_stream(self):
        if self.running:
            self._stop_stream("Đã ngắt 2 FSR")
            return

        try:
            serial_settings_list = self._serial_settings()
            ip, port, rate = self._connection_settings()
            packet_settings = self._packet_settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))
            return

        self.stop_playback(silent=True)
        self.clear_charts()
        self._reset_fsi()
        self._reset_zero('Kết nối mới: chưa lấy zero')
        self.running = True
        self.smoothed_matrices.clear()
        self.last_raw_matrices.clear()
        self.detected_sides.clear()
        self.connected_channels.clear()
        self.frame_counts = {1: 0, 2: 0}
        self.active_channels = {settings[0] for settings in serial_settings_list}
        self.workers = []
        self.module_code.set("Đang chờ LL/RR...")
        self.bt_button_text.set("Đang kết nối...")

        devices = ", ".join(settings[1] for settings in serial_settings_list)
        self.status.set(f"Đang kết nối {devices}...")
        for channel_id, device, baudrate, rows, columns, fallback_side in serial_settings_list:
            self._channel_status_var(channel_id).set(f"Đang mở {device}...")
            worker = threading.Thread(
                target=self._hardware_loop,
                args=(
                    channel_id,
                    (device, baudrate, rows, columns, fallback_side),
                    (ip, port, rate),
                    packet_settings,
                ),
                daemon=True,
                name=f"fsr-serial-{channel_id}",
            )
            self.workers.append(worker)
            worker.start()

    def _channel_status_var(self, channel_id):
        return self.channel_status_1 if channel_id == 1 else self.channel_status_2

    def _stop_stream(self, status_text=None):
        self.running = False
        self._reset_zero('Đã ngắt FSR: zero đã huỷ')
        self._reset_fsi()
        self.smoothed_matrices.clear()
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.active_channels.clear()
        self.connected_channels.clear()
        self.workers = []
        self.bt_button_text.set("Kết nối 2 FSR")
        self.module_code.set("--")
        self.channel_status_1.set("Đã ngắt")
        self.channel_status_2.set("Đã ngắt")
        self._set_connection_panel_collapsed(False)
        if self.log_handle is not None:
            self._stop_logging()
        if status_text:
            self.status.set(status_text)

    def _hardware_loop(self, channel_id, serial_settings, udp_settings, packet_settings):
        device, baudrate, rows, columns, fallback_side = serial_settings
        ip, port, rate = udp_settings
        min_period = 1.0 / rate
        last_send_time = 0.0
        last_ui_time = 0.0
        buffer_tokens = []
        detected_side = None
        ser = None

        try:
            ser = serial.Serial()
            ser.port = device
            ser.baudrate = baudrate
            ser.bytesize = serial.EIGHTBITS
            ser.parity = serial.PARITY_NONE
            ser.stopbits = serial.STOPBITS_ONE
            ser.timeout = DEFAULT_SERIAL_TIMEOUT
            ser.rtscts = False
            ser.dsrdtr = False
            for open_attempt in range(3):
                try:
                    ser.open()
                    break
                except (serial.SerialException, OSError):
                    if open_attempt == 2 or not self.running:
                        raise
                    time.sleep(1.0)
            # Bluetooth SPP does not need modem-control toggles. Some Windows
            # drivers disconnect briefly when DTR/RTS is forced, which looked
            # like the COM number was jumping between reconnect attempts.
            time.sleep(0.3)

            with self.serial_lock:
                self.serial_connections[channel_id] = ser
            ser.reset_input_buffer()
            self.root.after(0, self._on_connected, channel_id, device)

            while self.running:
                if ser.in_waiting > 2048:
                    ser.reset_input_buffer()
                    buffer_tokens.clear()
                    continue

                raw_line = ser.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                tokens = line.split()
                if not tokens:
                    continue

                if tokens[0].upper() in ("RR", "LL"):
                    raw_module = tokens[0].upper()

                    detected_side = "left" if raw_module == "RR" else "right"
                    buffer_tokens = tokens[1:]

                    actual_leg = 'Left' if raw_module == 'RR' else 'Right'
                    display_text = f"{raw_module} ({actual_leg})"

                    self.root.after(0, self.module_code.set, display_text)
                else:
                    buffer_tokens.extend(tokens)

                target_count = (rows * columns) if (rows and columns) else 48
                if len(buffer_tokens) > target_count * 8:
                    buffer_tokens = buffer_tokens[-target_count * 2:]
                if len(buffer_tokens) < target_count:
                    continue

                frame_tokens = buffer_tokens[:target_count]
                buffer_tokens = buffer_tokens[target_count:]
                try:
                    values = [float(value) for value in frame_tokens]
                    active_side = detected_side or fallback_side
                    matrix, frame_side = parse_hardware_frame(
                        values, active_side, rows, columns
                    )
                    incoming_raw_matrix = [row[:] for row in matrix]
                    raw_matrix = self._apply_ema_filter(channel_id, matrix)
                    selected_unit = self._selected_unit
                    now = time.monotonic()
                    matrix, zero_metadata = self._convert_live_matrix(
                        raw_matrix, selected_unit, frame_side, now)
                    self.last_raw_matrices[frame_side] = [row[:] for row in raw_matrix]
                    current_packet_settings = (
                        packet_settings[0], frame_side, selected_unit
                    )
                except (ValueError, TypeError) as exc:
                    self.root.after(
                        0,
                        self._channel_status_var(channel_id).set,
                        f"Lỗi frame: {exc}",
                    )
                    continue

                self.frame_counts[channel_id] += 1
                self._write_log_sample(
                    frame_side,
                    incoming_raw_matrix,
                    raw_matrix,
                    matrix,
                    selected_unit,
                    now,
                    zero_metadata,
                )

                if now - last_send_time >= min_period:
                    status = self._send_matrix_udp(
                        matrix, ip, port, current_packet_settings, zero_metadata
                    )
                    last_send_time = now

                if now - last_ui_time >= 0.04:
                    self.root.after(
                        0,
                        self._update_after_frame,
                        channel_id,
                        frame_side,
                        matrix,
                        selected_unit,
                        status,
                        zero_metadata,
                    )
                    last_ui_time = now

        except (serial.SerialException, OSError, ValueError) as exc:
            if self.running:
                self.root.after(
                    0, self._stream_failed, channel_id, device, str(exc)
                )
        finally:
            with self.serial_lock:
                current = self.serial_connections.get(channel_id)
                if current is ser:
                    self.serial_connections.pop(channel_id, None)
            if ser is not None:
                try:
                    ser.close()
                except (serial.SerialException, OSError):
                    pass
            self.root.after(0, self._channel_finished, channel_id)

    def _on_connected(self, channel_id, device):
        self.connected_channels.add(channel_id)
        self._channel_status_var(channel_id).set(f"{device}: chờ LL/RR")
        self.bt_button_text.set("Ngắt 2 FSR")
        self.status.set(f"Đã mở {device}; đang chờ dữ liệu")
        if self.active_channels and self.active_channels.issubset(self.connected_channels):
            self._set_connection_panel_collapsed(True)
            if self.main_notebook is not None and self.total_chart_tab is not None:
                self.main_notebook.select(self.total_chart_tab)

    def _on_module_detected(self, channel_id, raw_module, device):
        side = "right" if raw_module == "RR" else "left"
        self.detected_sides[channel_id] = side
        side_label = "Chân phải" if side == "right" else "Chân trái"
        self._channel_status_var(channel_id).set(f"{device}: {raw_module} - {side_label}")

        labels = []
        for current_channel in sorted(self.detected_sides):
            current_side = self.detected_sides[current_channel]
            code = "RR" if current_side == "right" else "LL"
            labels.append(f"FSR {current_channel}: {code}")
        duplicate = len(self.detected_sides) > 1 and len(set(self.detected_sides.values())) < len(
            self.detected_sides
        )
        self.module_code.set(" | ".join(labels) + (" (TRÙNG CHÂN)" if duplicate else ""))
        if duplicate:
            self.status.set("Cảnh báo: cả hai cổng đang gửi cùng LL hoặc cùng RR")

    def _update_after_frame(self, channel_id, frame_side, matrix, unit, status, zero_metadata=None):
        if not self.running:
            return
        if unit != self._selected_unit:
            return
        if unit == 'newton' and zero_metadata is not None and not self.shoe_zero.is_current(zero_metadata):
            return  # An older queued callback must not repaint after zero/reset.
        side_code = "LL" if frame_side == "left" else "RR"
        count = self.frame_counts[channel_id]
        self._channel_status_var(channel_id).set(f"{side_code}: đã nhận {count} frame")
        self.status.set(status)
        self.draw_matrix(matrix, frame_side, unit)
        self._append_chart_sample(frame_side, matrix, unit=unit)
        self._append_fsi_sample(frame_side, matrix, unit)

    def _stream_failed(self, channel_id, device, error_message):
        self._reset_zero('Mất kết nối: zero đã huỷ; kết nối lại rồi lấy zero')
        self.connected_channels.discard(channel_id)
        self._set_connection_panel_collapsed(False)
        self._channel_status_var(channel_id).set(f"{device}: l\u1ed7i m\u1edf c\u1ed5ng")
        self.status.set(f"L\u1ed7i {device}: {error_message}")
        messagebox.showwarning(
            f"FSR {channel_id} kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c",
            f"Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c {device}. C\u1ed5ng FSR c\u00f2n l\u1ea1i v\u1eabn ti\u1ebfp t\u1ee5c "
            f"n\u1ebfu k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c.\n\nChi ti\u1ebft: {error_message}\n\n"
            "H\u00e3y \u0111\u00f3ng Tera Term/Serial Monitor ho\u1eb7c \u1ee9ng d\u1ee5ng kh\u00e1c \u0111ang gi\u1eef c\u1ed5ng.",
        )

    def _channel_finished(self, channel_id):
        self._reset_zero('Cổng FSR đã đóng: zero đã huỷ')
        self.active_channels.discard(channel_id)
        self.connected_channels.discard(channel_id)
        if self.running and not self.active_channels:
            self.running = False
            self.bt_button_text.set("Kết nối 2 FSR")
            self.status.set("Không còn cổng FSR nào đang chạy")
            self._set_connection_panel_collapsed(False)
            if self.log_handle is not None:
                self._stop_logging()

    def draw_matrix(self, matrix, side=None, unit=None):
        matrix = validate_matrix(matrix)
        unit = unit or self._selected_unit
        min_force, max_force = color_range_for_unit(unit)
        side = side if side in ("left", "right") else self.side.get()
        canvas = self.canvas_left if side == "left" else self.canvas_right
        summary = self.summary_left if side == "left" else self.summary_right
        state = self.preview_state[side]

        rows = len(matrix)
        columns = len(matrix[0])
        width = max(canvas.winfo_width(), 210)
        height = max(canvas.winfo_height(), 300)

        if (
            state["shape"] != (rows, columns)
            or state["size"] != (width, height)
            or len(state["rects"]) != rows * columns
        ):
            canvas.delete("all")
            state["rects"] = []
            state["texts"] = []
            state["shape"] = (rows, columns)
            state["size"] = (width, height)

            cell_width = width / columns
            cell_height = height / rows
            for y in range(rows):
                for x in range(columns):
                    x0, y0 = x * cell_width, y * cell_height
                    x1, y1 = x0 + cell_width, y0 + cell_height
                    state["rects"].append(
                        canvas.create_rectangle(
                            x0, y0, x1, y1, fill="#111827", outline="#374151"
                        )
                    )
                    state["texts"].append(
                        canvas.create_text(
                            (x0 + x1) / 2,
                            (y0 + y1) / 2,
                            text="",
                            fill="#d1d5db",
                            font=("Consolas", 8),
                        )
                    )

        cell_width = width / columns
        cell_height = height / rows
        index = 0
        for row in matrix:
            for value in row:
                canvas.itemconfig(
                    state['rects'][index],
                    fill=get_force_color(value, min_force, max_force),
                )
                if cell_width >= 20 and cell_height >= 14:
                    text_color = (
                        "#111827"
                        if value >= (min_force + max_force) / 3
                        else "#ffffff"
                    )
                    value_text = f'{value:.2f}' if unit == 'newton' else f'{value:g}'
                    canvas.itemconfig(
                        state['texts'][index], text=value_text, fill=text_color
                    )
                else:
                    canvas.itemconfig(state["texts"][index], text="")
                index += 1

        total, cop_x, cop_y = matrix_summary(matrix)
        cop_text = "--" if cop_x is None else f"({cop_x:.2f}, {cop_y:.2f})"
        side_code = "LL" if side == "left" else "RR"
        summary.set(
            f'{side_code} | {rows}×{columns} | Tổng: {total:.2f} '
            f'{unit_label(unit)}\nCoP: {cop_text}'
        )

    def close(self):
        self.running = False
        self._reset_zero()
        self.stop_playback(silent=True)
        self._stop_logging("Đã đóng log")
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.socket.close()
        self.root.destroy()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='FSR transmitter; built-in experimental profiles for the measured pair.')
    parser.add_argument('--no-calibration', action='store_true', help='Use original force formula without cell correction')
    parser.add_argument('--right-calibration', type=Path)
    parser.add_argument('--left-calibration', type=Path)
    args = parser.parse_args()
    if args.no_calibration:
        CELL_CALIBRATIONS = {}
    elif args.right_calibration or args.left_calibration:
        # Explicit profile flags retain their original opt-in semantics.
        CELL_CALIBRATIONS = {}
    for side, profile_path in (('right', args.right_calibration), ('left', args.left_calibration)):
        if profile_path is None:
            continue
        from backend.fsr_force import apply_cell_calibration
        with profile_path.open(encoding='utf-8') as handle:
            profile = json.load(handle)
        if (profile.get('version') != 1 or profile.get('side') != side
                or not profile.get('id') or not profile.get('status')):
            raise ValueError(f'Unsupported {side} calibration profile')
        apply_cell_calibration([[0.0]*4 for _ in range(12)], side, profile)
        CELL_CALIBRATIONS[side] = profile
    window = tk.Tk()
    app = FSRTransmitterApp(window)
    if CELL_CALIBRATIONS:
        notes = []
        for side, profile in CELL_CALIBRATIONS.items():
            pending = [(r+1, c+1) for r, row in enumerate(profile['cells'])
                       for c, cell in enumerate(row) if cell is None]
            label = 'Phải' if side == 'right' else 'Trái'
            notes.append(f'{label}: các ô (hàng, cột) CHƯA hiệu chỉnh: {pending}')
            if profile.get('id') == 'right-20260929-three-point-v4':
                notes.append('Phải: 18 ô thử ba mốc 0 / 14,4 / 17,66 N; còn lại giữ hệ số cũ.')
                notes.append(f'Phải: cần đo lại (hàng, cột): {RIGHT_THREE_POINT_RETEST_CELLS}')
        window.title(window.title() + ' | HIỆU CHỈNH THỬ: ' + ', '.join(CELL_CALIBRATIONS))
        messagebox.showinfo('Hiệu chỉnh sơ bộ FSR',
                            'Chỉ dùng với đúng các miếng đã đo và cùng cách lắp.\n'
                            'Chọn Newton để áp dụng. ADC và bên không nạp profile giữ nguyên.\n'
                            'Chưa kiểm chứng toàn dải lực. Dùng nút Zero khi mang giày, chân không chịu tải.\n'
                            'Hiệu chỉnh sơ bộ; cần cân lại cả lúc tăng và giảm tải.\n'
                            'Mở với --no-calibration để trở về công thức cũ.\n'
                            + '\n'.join(notes))
    window.mainloop()
