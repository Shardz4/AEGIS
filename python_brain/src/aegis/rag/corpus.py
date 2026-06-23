from dataclasses import dataclass

@dataclass
class Document:
    doc_id: str
    source: str          # e.g., "OISD-STD-116", "OSHA 29 CFR 1910.119", etc.
    section: str         # e.g., "Section 5.3 - Gas Monitoring"
    text: str            # Detailed regulatory text (300-500 words per chunk)
    keywords: list[str]  # Fallback keywords for matching

def get_mock_corpus() -> list[Document]:
    return [
        # OISD-STD-116 (Fire Protection)
        Document(
            doc_id="OISD-116-01",
            source="OISD-STD-116",
            section="Section 5.1 - Hot Work Authorization and Permit Control",
            text=(
                "All hot work activities in hazardous areas, such as process units, tank farms, pump stations, "
                "and piping racks, must be governed by a formal Permit-to-Work (PTW) system. No hot work shall "
                "commence without written authorization from the area supervisor. Before issuing a permit, the area "
                "must be inspected, isolated from sources of flammable liquids or gases, and depressurized. Any equipment "
                "where work is to be done must be purged with steam or inert gas, blinded, and certified gas-free. "
                "The permit must detail the specific tools to be used, safety precautions required, fire-fighting "
                "equipment to be kept standby, and the validity duration of the permit. The permit shall be signed "
                "by both the issuer and the receiver, and copy displayed at the work site."
            ),
            keywords=["hot work", "permit", "ptw", "authorization", "fire fighting", "hazardous area"]
        ),
        Document(
            doc_id="OISD-116-02",
            source="OISD-STD-116",
            section="Section 5.3 - Gas Monitoring and LEL Limits during Hot Work",
            text=(
                "Prior to the commencement of any hot work operations in areas where flammable gases or vapours "
                "may be present, continuous or periodic gas monitoring must be established. Gas concentration "
                "must be tested using a calibrated combustible gas detector. The gas concentration must not exceed "
                "10% of the Lower Explosive Limit (LEL) at any point during hot work operations. If the LEL level "
                "crosses 10%, all work must be suspended immediately, the permit revoked, and the area evacuated. "
                "For high-risk areas, continuous gas monitors with audible and visual alarms must be positioned "
                "near the hot work location. Periodic re-tests must be conducted every two hours if continuous "
                "monitoring is not deployed, and recorded on the permit log sheet."
            ),
            keywords=["gas monitoring", "lel", "hot work", "flammable gas", "vapour", "gas detector"]
        ),
        Document(
            doc_id="OISD-116-03",
            source="OISD-STD-116",
            section="Section 6.2 - Fire Water Availability and Pressure Requirements",
            text=(
                "The plant fire water network must maintain a continuous pressure of not less than 7.0 kg/cm² "
                "at the farthest point of the distribution system. The fire water pumps must be configured with "
                "auto-start mechanisms triggered by pressure drops in the header. Standby diesel-driven pumps "
                "must be available to start within 30 seconds of utility power failure. At least two independent "
                "fire water monitors or hose stations must be capable of reaching any point within a process unit. "
                "During hot work, a pressurized fire hose with a fog nozzle must be laid out and kept ready for "
                "immediate use. Water spray systems for reactors and vessel dikes must be tested quarterly."
            ),
            keywords=["fire water", "pressure", "pumps", "hose", "reactor spray", "deluge"]
        ),
        Document(
            doc_id="OISD-116-04",
            source="OISD-STD-116",
            section="Section 7.1 - Gas Detector Placement and Alarm Thresholds",
            text=(
                "Hydrocarbon gas detectors must be installed at all potential leak sources, including compressor "
                "seals, pump glands, valve manifolds, and separator outlets. Detectors should be positioned based "
                "on gas density: light gases (methane, hydrogen) require sensors at high elevations, while heavy gases "
                "(butane, propane, H2S) require sensors near ground level. Low-alarm thresholds must be set at 20% "
                "LEL, triggering control room alerts and local beacons. High-alarm thresholds must be set at 50% "
                "LEL, triggering automatic isolation of feed valves, activation of water deluge systems, and "
                "operator emergency action. Daily calibration checks are required for critical sensors."
            ),
            keywords=["gas detector", "alarm threshold", "lel", "compressor seal", "hydrocarbon", "deluge"]
        ),
        Document(
            doc_id="OISD-116-05",
            source="OISD-STD-116",
            section="Section 8.4 - Emergency Shutdown Systems (ESD) Activation",
            text=(
                "The Emergency Shutdown System (ESD) must be designed to fail-safe and operate independently of "
                "the basic process control system (BPCS). Activation of the ESD must occur automatically upon "
                "detection of process parameters exceeding critical safety limits, including: reactor high-high "
                "temperature, separator high-high level, pipeline low-low pressure, or triple-modular redundant "
                "(TMR) gas detection high-alarm. Manual ESD activation buttons (break-glass stations) must be "
                "located at all main escape routes, control room exits, and field operator shelters. Emergency "
                "depressurization valves (EDPV) must route inventory to the flare stack within 15 minutes."
            ),
            keywords=["emergency shutdown", "esd", "fail-safe", "depressurization", "critical limit", "flare"]
        ),

        # OISD-STD-144 (PTW & Confined Space)
        Document(
            doc_id="OISD-144-01",
            source="OISD-STD-144",
            section="Section 4.1 - Permit-to-Work (PTW) System Administration",
            text=(
                "The Permit-to-Work (PTW) system is a core administrative control designed to prevent unauthorized "
                "or conflicting activities in the plant. Permits are categorized into Hot Work, Cold Work, Confined "
                "Space Entry, Lockout/Tagout (LOTO), and Electrical Work. An issuer (typically the shift in-charge) "
                "must verify that the plant is in a safe condition before authorizing work. The receiver (maintenance "
                "supervisor) is responsible for executing work in accordance with permit conditions. No two conflicting "
                "permits (such as a Hot Work permit and a Line Break permit on the same line) shall be active "
                "simultaneously in the same zone. Permits must be re-validated at the change of every shift."
            ),
            keywords=["permit to work", "ptw", "cold work", "loto", "issuer", "receiver", "conflicting permits"]
        ),
        Document(
            doc_id="OISD-144-02",
            source="OISD-STD-144",
            section="Section 4.3 - Gas Testing for Confined Space Entry",
            text=(
                "Before any personnel enters a confined space (vessels, columns, storage tanks, pits), a qualified "
                "gas tester must perform internal atmosphere checks. The oxygen level must be between 19.5% and "
                "23.5% by volume. Toxic gases must be below their respective occupational exposure limits (H2S < 5 ppm, "
                "CO < 25 ppm). Combustible gas concentration must be 0% LEL. The gas testing instrument must be "
                "zeroed and calibrated. Initial tests must be performed from the outside using sampling tubes. "
                "Testing must be done at the top, middle, and bottom sections of the vessel to detect stratified gases. "
                "Results must be recorded on the entry permit prior to sign-off."
            ),
            keywords=["gas testing", "confined space", "oxygen", "toxic gas", "h2s", "co", "lel"]
        ),
        Document(
            doc_id="OISD-144-03",
            source="OISD-STD-144",
            section="Section 5.2 - Isolation of Energy Sources (LOTO)",
            text=(
                "Physical isolation of process equipment is mandatory before cold or hot work begins. Isolation must "
                "be achieved through positive means, such as inserting blinds/spectacle flanges or disconnecting "
                "piping spools. Closed valves alone are not sufficient isolation for hot work or vessel entry. "
                "All electrical power supplies to motors, agitators, and heaters must be locked out at the Motor "
                "Control Center (MCC) with personal padlocks and danger tags. Lockout/Tagout (LOTO) procedures "
                "must be verified by a field bump test of the starter button. Energy isolation logs must be "
                "maintained and attached to the work permit."
            ),
            keywords=["isolation", "loto", "blind", "flange", "lockout", "mcc", "energy source"]
        ),
        Document(
            doc_id="OISD-144-04",
            source="OISD-STD-144",
            section="Section 6.1 - Rescue and Standby Personnel for Vessel Entry",
            text=(
                "For every permit-required confined space entry, at least one trained standby person (hole watch) "
                "must be stationed outside the entry point. The standby person must maintain continuous visual "
                "or radio contact with the entrants. Under no circumstances shall the standby person enter the "
                "space to attempt rescue unless relieved by other standby staff and wearing a self-contained breathing "
                "apparatus (SCBA). A rescue tripod with a mechanical winch, harness, and lifeline must be set up "
                "at the manway. An emergency oxygen pack, SCBA, and resuscitation kit must be kept standby at the "
                "entry platform. The local fire station must be notified prior to entry."
            ),
            keywords=["standby person", "rescue", "vessel entry", "scba", "tripod", "lifeline", "hole watch"]
        ),
        Document(
            doc_id="OISD-144-05",
            source="OISD-STD-144",
            section="Section 7.3 - Cold Work Permit Conditions",
            text=(
                "Cold work permits cover activities that do not generate heat or sparks, such as bolt tensioning, "
                "filter replacement, lubrication, insulation work, and structural painting. While inherently safer "
                "than hot work, cold work still requires hazard identification. Personal protective equipment (PPE) "
                "including safety goggles, chemical-resistant gloves, and safety harnesses for height work must "
                "be specified. Area gas checks are required if work is done near active hydrocarbon lines. "
                "The permit must list all isolated energy sources and check for hazardous chemical residue. "
                "Housekeeping must be maintained, and scaffolding must be tagged safe before use."
            ),
            keywords=["cold work", "ppe", "insulation", "painting", "scaffolding", "chemical residue"]
        ),

        # OSHA 29 CFR 1910.119 (Process Safety Management)
        Document(
            doc_id="OSHA-119-01",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(d) - Process Safety Information (PSI)",
            text=(
                "The employer shall complete a compilation of written process safety information before conducting "
                "any process hazard analysis. The process safety information shall include information pertaining "
                "to the hazards of the highly hazardous chemicals used or produced by the process, including toxicity, "
                "permissible exposure limits, physical data, reactivity, corrosive data, thermal and chemical stability. "
                "Information pertaining to the technology of the process shall include a block flow diagram, "
                "process chemistry, maximum intended inventory, and safe upper and lower limits for temperatures, "
                "pressures, flows, or compositions. Piping and Instrument Diagrams (P&IDs) must be up to date."
            ),
            keywords=["process safety information", "psi", "chemistry", "inventory", "temperature limit", "p&id"]
        ),
        Document(
            doc_id="OSHA-119-02",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(e) - Process Hazard Analysis (PHA) requirements",
            text=(
                "The employer shall perform a process hazard analysis (hazard evaluation) on processes covered "
                "by this standard. The PHA shall be appropriate to the complexity of the process and shall identify, "
                "evaluate, and control the hazards involved in the process. The employer shall use one or more of the "
                "following methodologies: What-If, Checklist, Hazard and Operability Study (HAZOP), Failure Mode "
                "and Effects Analysis (FMEA), or Fault Tree Analysis. The PHA shall address the hazards of the process, "
                "the identification of any previous incident which had a likely potential for catastrophic consequences, "
                "engineering and administrative controls, detection methods, and human factors."
            ),
            keywords=["process hazard analysis", "pha", "hazop", "fmea", "human factors", "consequences"]
        ),
        Document(
            doc_id="OSHA-119-03",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(f) - Operating Procedures and Emergency Steps",
            text=(
                "The employer shall develop and implement written operating procedures that provide clear instructions "
                "for safely conducting activities involved in each covered process. Operating procedures shall address "
                "steps for each operating phase: initial startup, normal operations, temporary operations, emergency "
                "shutdown (including conditions requiring shutdown and assignment of shutdown responsibility), "
                "emergency operations, and normal shutdown. Operating limits must state the consequences of deviation "
                "and steps required to correct or avoid deviations. Safety and health considerations must cover "
                "precautions to prevent exposure and control chemical release."
            ),
            keywords=["operating procedures", "emergency shutdown", "operating limit", "deviation", "chemical release"]
        ),
        Document(
            doc_id="OSHA-119-04",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(h) - Contractor Safety Management",
            text=(
                "The employer, when selecting a contractor, shall obtain and evaluate information regarding the "
                "contractor employer's safety performance and programs. The employer shall inform contractor "
                "employers of the known potential fire, explosion, or toxic release hazards related to the contractor's "
                "work and the process. The employer shall explain to contractor employers the emergency action plan. "
                "Contractor employers shall assure that each contractor employee is trained in the work practices "
                "necessary to safely perform his or her job, follows the safety rules of the facility, and documents "
                "that each employee has received and understood the training."
            ),
            keywords=["contractor", "safety performance", "emergency plan", "training", "work practices"]
        ),
        Document(
            doc_id="OSHA-119-05",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(j) - Mechanical Integrity of Critical Equipment",
            text=(
                "The employer shall establish and implement written procedures to maintain the on-going integrity of "
                "process equipment. Process equipment includes: pressure vessels and storage tanks, piping systems "
                "(including piping components such as valves), relief and vent systems and devices, emergency "
                "shutdown systems, controls (including monitoring devices and sensors, alarms, and interlocks), and "
                "pumps. Inspection and testing shall be performed on process equipment. Inspection and testing "
                "procedures shall follow recognized and generally accepted good engineering practices (RAGAGEP). "
                "The frequency of inspections shall be consistent with manufacturer's recommendations or historical data."
            ),
            keywords=["mechanical integrity", "inspection", "testing", "ragagep", "pressure vessel", "sensor", "interlock"]
        ),
        Document(
            doc_id="OSHA-119-06",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(l) - Management of Change (MOC) Procedures",
            text=(
                "The employer shall establish and implement written procedures to manage changes (except for 'replacements "
                "in kind') to process chemicals, technology, equipment, and procedures; and, changes to facilities "
                "that affect a covered process. The procedures shall assure that the following considerations are "
                "addressed prior to any change: the technical basis for the proposed change, impact of change on safety "
                "and health, modifications to operating procedures, necessary time period for the change, and "
                "authorization requirements. Employees involved in operating and maintaining the process shall be "
                "informed of, and trained in, the change prior to start-up of the process."
            ),
            keywords=["management of change", "moc", "replacement in kind", "technical basis", "training"]
        ),
        Document(
            doc_id="OSHA-119-07",
            source="OSHA 29 CFR 1910.119",
            section="1910.119(n) - Emergency Planning and Response",
            text=(
                "The employer shall establish and implement an emergency action plan for the entire plant in "
                "accordance with the provisions of 29 CFR 1910.38. In addition, the emergency action plan shall "
                "include procedures for handling small releases of hazardous chemicals. Employers covered under "
                "this standard may also be subject to the hazardous waste and emergency response (HAZWOPER) provisions "
                "in 29 CFR 1910.120(a), (p), and (q). Pre-planned evacuation routes, assembly points, and alarm "
                "systems must be periodically tested. Emergency responder roles, incident command structure, and "
                "mutual aid agreements must be documented."
            ),
            keywords=["emergency planning", "evacuation", "chemical release", "hazwoper", "alarm"]
        ),

        # OSHA 29 CFR 1910.146 (Confined Space Entry)
        Document(
            doc_id="OSHA-146-01",
            source="OSHA 29 CFR 1910.146",
            section="1910.146(c) - Permit-Required Confined Space Program",
            text=(
                "The employer shall decide if the workplace contains permit-required confined space entry points. "
                "If the workplace contains permit spaces, the employer shall inform exposed employees, by posting "
                "danger signs or by any other equally effective means, of the existence and location of and the danger "
                "posed by the permit spaces. A sign reading 'DANGER -- PERMIT-REQUIRED CONFINED SPACE, DO NOT ENTER' "
                "would satisfy this requirement. If the employer decides that its employees will enter permit spaces, "
                "the employer shall develop and implement a written permit space program. The program must include "
                "measures to prevent unauthorized entry, identify hazards, and establish safe entry conditions."
            ),
            keywords=["permit required", "confined space", "danger sign", "entry program", "hazard identification"]
        ),
        Document(
            doc_id="OSHA-146-02",
            source="OSHA 29 CFR 1910.146",
            section="1910.146(d) - Entry Procedures and Atmospheric Monitoring",
            text=(
                "Under the written permit space program, the employer shall identify and evaluate the hazards of "
                "permit spaces before employees enter them; specify acceptable entry conditions; isolate the permit "
                "space; purge, inert, flush, or ventilate the permit space as necessary to eliminate or control "
                "atmospheric hazards; provide pedestrian, vehicle, or other barriers to protect entrants; and "
                "test conditions in the permit space before entry operations are authorized. Testing must check "
                "first for oxygen, second for combustible gases and vapours, and third for toxic air contaminants. "
                "Continuous monitoring is required if atmospheric conditions can change."
            ),
            keywords=["entry procedures", "atmospheric monitoring", "oxygen", "combustible gas", "toxic", "purge"]
        ),
        Document(
            doc_id="OSHA-146-03",
            source="OSHA 29 CFR 1910.146",
            section="1910.146(e) - Entry Permit System and Authorization",
            text=(
                "Before entry is authorized, the employer shall document that the measures required by paragraph (d) "
                "of this section have been completed by preparing an entry permit. Before entry begins, the entry "
                "supervisor named on the permit shall sign the entry permit to authorize entry. The completed permit "
                "shall be made available to all eligible entrants, by posting it at the entry portal. The duration "
                "of the permit may not exceed the time required to complete the assigned task. The entry supervisor "
                "shall terminate entry and cancel the permit when the entry operations have been completed or when "
                "conditions that are not allowed under the entry permit arise in or near the permit space."
            ),
            keywords=["entry permit", "authorization", "supervisor signature", "cancel permit", "acceptable conditions"]
        ),
        Document(
            doc_id="OSHA-146-04",
            source="OSHA 29 CFR 1910.146",
            section="1910.146(k) - Rescue and Emergency Services",
            text=(
                "The employer shall designate a rescue team that is trained and equipped to perform confined space "
                "rescues. Non-entry rescue systems or methods shall be used unless the rescue equipment would increase "
                "the risk of entry. Each authorized entrant shall use a chest or full-body harness, with a retrieval "
                "line attached to the center of the entrant's back. The other end of the retrieval line shall be "
                "secured to a mechanical device (such as a winch on a tripod) so that rescue can begin immediately. "
                "Rescue teams must practice making rescues at least once every 12 months in representative spaces. "
                "Rescuers must be certified in CPR and first aid."
            ),
            keywords=["rescue team", "retrieval line", "winch", "tripod", "harness", "cpr", "first aid"]
        ),

        # NFPA 30 (Flammable Liquids Code)
        Document(
            doc_id="NFPA-30-01",
            source="NFPA 30",
            section="Chapter 6 - Piping System and Fire Protection",
            text=(
                "Piping systems containing flammable or combustible liquids must be designed, fabricated, and "
                "tested in accordance with recognized standards (e.g. ASME B31.3). Piping systems must be supported, "
                "anchored, and protected against physical damage. Steel piping must be used unless temperature or "
                "corrosivity requires alternative materials. Valves must be positioned to control flow and isolate "
                "equipment during emergencies. Emergency shutoff valves must be steel and designed to close automatically "
                "in a fire. Hose connections must be tested annually, and piping networks must be grounded to prevent "
                "static electricity buildup during transfer operations."
            ),
            keywords=["piping system", "valves", "static electricity", "asme b31.3", "emergency shutoff", "grounding"]
        ),
        Document(
            doc_id="NFPA-30-02",
            source="NFPA 30",
            section="Chapter 17 - Aboveground Tank Storage and Diking",
            text=(
                "Aboveground storage tanks for flammable liquids must be located with adequate spacing from property "
                "lines and adjacent vessels to prevent fire exposure. Tanks must be surrounded by a diked area "
                "capable of holding the full volume of the largest tank plus a margin for rainwater. The dike walls "
                "must be constructed of reinforced concrete, steel, or compacted earth, and engineered to be liquid-tight. "
                "Drainage valves for diked areas must be kept closed and locked, and only opened under supervision "
                "to discharge clean storm water. Internal foam deluge connections and cooling water rings must be "
                "maintained on all volatile product tanks."
            ),
            keywords=["storage tank", "dike", "spacing", "vessel containment", "drainage valve", "foam deluge"]
        ),
        Document(
            doc_id="NFPA-30-03",
            source="NFPA 30",
            section="Chapter 22 - Venting Requirements for Storage Tanks",
            text=(
                "Storage tanks containing flammable liquids must be equipped with normal and emergency venting systems. "
                "Normal venting must be sized to prevent vacuum or pressure buildup during liquid filling or withdrawal "
                "and thermal expansion. Emergency venting must allow the rapid release of vapours generated by exposure "
                "to external fire. Pressure-vacuum (PV) valves must be installed on all tanks storing Class I liquids. "
                "Flame arresters must be fitted on vent pipes discharging to the atmosphere. Vent outlets must "
                "terminate at a height and location that prevents vapour accumulation near building openings or "
                "electrical ignition sources."
            ),
            keywords=["tank venting", "pv valve", "emergency vent", "flame arrester", "vapour accumulation"]
        ),
        Document(
            doc_id="NFPA-30-04",
            source="NFPA 30",
            section="Chapter 27 - Electrical Classification and Ignition Sources",
            text=(
                "Area classification must be established for all locations handling flammable liquids. Class I, "
                "Division 1 locations include areas where flammable gas/vapour concentrations exist continuously or "
                "frequently during normal operations. Class I, Division 2 locations include areas where vapours are "
                "handled in closed systems and only escape during failures. All electrical equipment, wiring, and "
                "junction boxes in classified areas must be explosion-proof and intrinsically safe. Open flames, "
                "welding, smoking, and non-certified electrical devices are strictly prohibited in classified zones. "
                "Grounding straps must be bonded to all transfer piping."
            ),
            keywords=["electrical classification", "explosion proof", "class i div 1", "intrinsically safe", "grounding", "ignition source"]
        ),

        # API RP 752 (Plant Spacing and occupied buildings)
        Document(
            doc_id="API-752-01",
            source="API RP 752",
            section="Section 4.2 - Location of Control Rooms and Process Hazards",
            text=(
                "Occupied buildings, particularly plant control rooms, laboratory buildings, and operator shelters, "
                "must be located at safe distances from process hazards to protect personnel from blast overpressure, "
                "thermal radiation, and toxic gas exposure. Building location evaluations must utilize Quantitative "
                "Risk Assessment (QRA) models. If a control room is located within a potential blast zone, it must "
                "be designed to withstand the maximum predicted explosion overpressure (typically 0.3 to 0.5 bar "
                "for refinery blast walls). Ventilation intakes must be equipped with automated toxic gas detectors "
                "that close dampers within 10 seconds of alarm trip."
            ),
            keywords=["control room", "blast zone", "overpressure", "toxic gas", "dampers", "qra"]
        ),
        Document(
            doc_id="API-752-02",
            source="API RP 752",
            section="Section 5.3 - Spacing between Compressors and Process Vessels",
            text=(
                "High-pressure hydrocarbon gas compressors must be spaced at least 30 meters away from major process "
                "vessels, such as distillation columns, separators, and chemical reactors. This spacing reduces "
                "the risk of a mechanical compressor failure (such as a thrown rod or casing rupture) causing "
                "domino-effect damage to neighbouring high-inventory units. In addition, spacing prevents small gas "
                "leaks at compressor glands from accumulating and finding ignition sources. Elevated flare stacks "
                "must be positioned downwind and located at least 60 meters from any active process vessels."
            ),
            keywords=["compressor spacing", "process vessel", "domino effect", "flare stack", "hydrocarbon gas"]
        ),
        Document(
            doc_id="API-752-03",
            source="API RP 752",
            section="Section 6.1 - Blast-Resistant Building Design",
            text=(
                "Blast-resistant buildings (BRBs) in petrochemical complexes must be designed using dynamic structural "
                "analysis. Reinforced concrete walls and roofs must be engineered to resist ductile deformation "
                "without structural collapse. Windows must be prohibited or constructed from heavy blast-resistant "
                "laminated glass. Cable and piping penetrations through blast walls must be sealed with certified "
                "fire-and-gas-tight transits. Doors must open outward and have heavy mechanical latch systems. "
                "Structural columns must have double-tie reinforcement to prevent buckling from lateral blast waves."
            ),
            keywords=["blast resistant", "dynamic analysis", "laminated glass", "door latch", "concrete wall"]
        ),

        # IS 15656 (Hazardous Area Classification)
        Document(
            doc_id="IS-15656-01",
            source="IS 15656",
            section="Section 5.2 - Zone 0 Classification and Design Limits",
            text=(
                "Zone 0 is defined as an area in which an explosive gas atmosphere is present continuously or "
                "for long periods or frequently. Typical Zone 0 locations include the interior of storage tanks, "
                "the vapor space above volatile liquids in separator vessels, and the interior of closed piping "
                "systems. Only electrical equipment specifically certified as intrinsically safe (Ex 'ia') is "
                "permitted within Zone 0. No hot work, open flame, or spark-generating tools are allowed under any "
                "circumstances. Maintenance inside Zone 0 requires complete shutdown, draining, venting, and "
                "purging to establish a certified non-hazardous atmosphere."
            ),
            keywords=["zone 0", "intrinsically safe", "storage tank", "vapor space", "purging", "maintenance"]
        ),
        Document(
            doc_id="IS-15656-02",
            source="IS 15656",
            section="Section 5.3 - Zone 1 Classification and Equipment Rules",
            text=(
                "Zone 1 is defined as an area in which an explosive gas atmosphere is likely to occur in normal "
                "operation occasionally. Typical Zone 1 locations include the immediate vicinity of tank vents, "
                "sampling points, pump seals, and relief valves. Electrical equipment in Zone 1 must be explosion-proof "
                "(Ex 'd'), flameproof, or increased safety (Ex 'e'). Hot work permits in Zone 1 require stringent "
                "preconditions, including local isolation, continuous LEL monitoring, fire barriers, and backup "
                "water monitors. Spark-resistant hand tools (e.g., bronze or copper-beryllium) must be used for "
                "cold maintenance."
            ),
            keywords=["zone 1", "explosion proof", "relief valve", "leakage", "lel monitoring", "bronze tools"]
        ),
        Document(
            doc_id="IS-15656-03",
            source="IS 15656",
            section="Section 5.4 - Zone 2 Classification and Ventilation",
            text=(
                "Zone 2 is defined as an area in which an explosive gas atmosphere is not likely to occur in normal "
                "operation but, if it does occur, will persist for a short period only. Typical Zone 2 locations "
                "include areas surrounding Zone 1 boundaries, flange connections in outdoor piping racks, and pump "
                "rooms with adequate mechanical ventilation. Electrical equipment must be non-sparking (Ex 'n'). "
                "Ventilation systems in pump rooms must provide at least 12 air changes per hour to prevent vapor "
                "buildup. If mechanical ventilation fails, alarms must sound in the control room and the area "
                "must be re-classified as Zone 1."
            ),
            keywords=["zone 2", "ventilation", "non sparking", "flange leak", "air changes", "pump room"]
        )
    ]
