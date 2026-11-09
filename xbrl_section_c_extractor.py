"""
xbrl_section_c_extractor.py
Stage 2 Module: Structured Section C Extraction from SEBI BRSR XBRL Instance Filings.

Project Context & Motivation:
    In PDF extraction, corporate annual report designers render tabular data and multi-column
    narratives using visual layout grids, which can cause 'table bleed' and column scrambling
    when processed by standard text extractors.

    XBRL is the definitive long-term solution to this problem:
    1. Tables and disclosures are natively stored as structured XML tags with explicit
       contextual dimensions (e.g. axes for gender, plant locations, worker categories).
    2. Explanatory narratives are stored in dedicated text blocks (e.g. *ExplanatoryTextBlock).
    3. Assurance metadata (BRSR Core assurance status) is stored explicitly as machine-readable
       flags for every principle.

Usage:
    python xbrl_section_c_extractor.py path/to/filing.xml
    Example:
        python xbrl_section_c_extractor.py data/raw/filings/Infosys.xml
"""

from dataclasses import dataclass
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from schema import BRSRRow


# ==============================================================================
# SEBI BRSR Taxonomy Keyword Mappings for Principles 1–9
# ==============================================================================

PRINCIPLE_TAXONOMY_MAP = {
    1: {
        "name": "Ethics, Transparency & Accountability",
        "leadership_patterns": [
            r"valuechainpartner",
            r"awarenessprogramme.*valuechain",
            r"avoid.*manage.*conflict.*interest",
            r"conflict.*interest.*board",
            r"conflictsofinterestinvolvingmembersoftheboard",
        ],
        "essential_patterns": [
            r"trainingandawareness",
            r"finesorpenalties",
            r"disciplinaryaction",
            r"anticorruption",
            r"antibribery",
            r"conflict.*interest",
            r"accountspayable",
            r"concentrationofpurchase",
            r"concentrationofsale",
            r"codeofconduct",
            r"awarenessprogramme",
            r"topicsorprinciplescoveredunderthetraining",
            r"monetarycasefor",
            r"amountofsettlement",
            r"appealbeenpreferred",
            r"regulatoryorenforcementagencies",
            r"ngrbcprincipleforpenaltyorfine",
            r"ngrbcprincipleforsettlement",
            r"tradinghouse",
            r"dealersordistributors",
            r"relatedpart",
            r"principle1",
        ],
    },
    2: {
        "name": "Sustainable & Safe Products",
        "leadership_patterns": [
            r"lifecycle.*assessment",
            r"lifecycleperspective",
            r"recycled.*reused.*input",
            r"inputmaterial.*recycled",
            r"reusedorcycled",
            r"reclaimedproduct",
            r"packagingmaterial.*reclaimed",
            r"significant.*social.*environmental.*concern",
        ],
        "essential_patterns": [
            r"randd.*capitalexpenditure",
            r"sustainablesourcing",
            r"reclaim.*product.*endoflife",
            r"wastecollectionplan",
            r"extendedproducerresponsibility",
            # NOTE: a bare "epr" pattern was removed: as a substring it matched unrelated tags
            # ("ThEPRocesses", "ProvidEr", "ReprEsent"). EPR is covered by the full phrase above.
            r"sustainableproduct",
            r"sustainably",
            r"duetorandd",
            r"duetocapex",
            r"percentageofrandd",
            r"percentageofcapex",
            r"amountof(?:reused|recycled|safelydisposed)",
            r"recyclingandorsafedisposal",
            r"safeandresponsibleusage",
            r"principle2",
        ],
    },
    3: {
        "name": "Employee Wellbeing & Fair Wages",
        "leadership_patterns": [
            r"lifeinsurance",
            r"compensatorypackage",
            r"statutorydues.*valuechain",
            r"highconsequence",
            r"transitionassistance",
            r"assessment.*valuechain.*p3",
            r"workingconditions.*valuechain",
            r"healthandsafetypractices.*valuechain",
            r"safetyrelatedincident.*valuechain",
            r"plantandoffice.*assessment",
            r"differentlyabled.*visitor",
        ],
        "essential_patterns": [
            r"wellbeing",
            r"retirementbenefit",
            r"accessible.*differentlyabled.*employee",
            r"differentlyabledemployee",
            r"equalopportunity",
            r"returntowork",
            r"retentionrate",
            r"grievance.*redressal.*employee",
            r"grievance.*redressal.*worker",
            r"union",
            r"association.*union",
            r"training.*skill",
            r"training.*health.*safety",
            r"performance.*career.*review",
            r"healthandsafety",
            r"workrelatedinjury",
            r"losttimeinjury",
            r"fatality",
            r"fatalities",
            r"posh",
            r"sexualharassment",
            r"discrimination.*workplace",
            r"childlabour",
            r"forcedlabour",
            r"minimumwage",
            r"safeandhealthyworkplace",
            r"redressgrievances.*(?:employee|worker)",
            r"correctiveaction.*safetyrelatedincident",
            r"correctiveaction.*assessment.*plant",
            r"equaloppertunity",
            r"workrelatedinjur",
            r"nonoccupationalmedical",
            r"turnoverrate",
            r"trainedemployeesorworkers",
            r"formembership",
            r"performanceandcareerdevelopment",
            r"coveredaspercentageoftotal(?:employees|worker)",
            r"deductedanddepositedwiththeauthority",
            r"rehabilitatedandplaced",
            r"totalnumberofaffected",
            r"assessedp3",
            r"identifyworkrelatedhazards",
            r"principle3",
        ],
    },
    4: {
        "name": "Stakeholder Responsiveness",
        "leadership_patterns": [
            r"consultationbetweenstakeholdersandtheboard",
            r"stakeholderconsultation.*support",
            r"engagementwithandactionstakentoaddresstheconcernsofvulnerable",
            r"vulnerable.*marginalized.*stakeholder",
            r"inputsreceivedfromstakeholders",
        ],
        "essential_patterns": [
            r"identifyingkeystakeholder",
            r"keystakeholdergroup",
            r"frequencyofengagement",
            r"complaints.*stakeholdergroup",
            r"stakeholdergroup",
            r"purposeandscopeofengagement",
            r"channelsofcommunication",
            r"principle4",
        ],
    },
    5: {
        "name": "Human Rights",
        "leadership_patterns": [
            r"businessprocess.*modified.*humanrights",
            r"humanrightsduediligence",
            r"humanrights.*duediligence",
            r"duediligence.*humanrights",
            r"businessagreements.*humanrights",
            r"assessment.*valuechain.*p5",
            r"valuechainpartner.*p5",
            r"valuechainpartner.*humanrights",
            r"correctiveaction.*valuechainpartner.*assessment",
        ],
        "essential_patterns": [
            r"training.*humanrights",
            r"humanrights.*training",
            r"minimumwages",
            r"median.*remuneration",
            r"focalpoint.*humanrights",
            r"humanrights.*grievance",
            r"humanrights.*complaint",
            r"preventadverseconsequences",
            r"humanrights",
            r"grosswages",
            r"totalwagespaid",
            r"assessedp5",
            r"principle5",
        ],
    },
    6: {
        "name": "Environment & Climate",
        "leadership_patterns": [
            r"waterstress",
            r"areasofwaterstress",
            r"scope3",
            r"biodiversity",
            r"ecologicallysensitive",
            r"cleantechnology",
            r"environmental.*assessment.*valuechain",
            r"valuechain.*environmentalimpact",
            r"greencredit",
        ],
        "essential_patterns": [
            r"energyconsumption",
            r"energyconsumed",
            r"energyintensity",
            r"waterwithdrawal",
            r"waterdischarge",
            r"waterconsumption",
            r"waterintensity",
            r"zeroliquiddischarge",
            r"airemissions",
            r"greenhousegas",
            r"ghg",
            r"scope1",
            r"scope2",
            r"reducinggreenhousegas",
            r"wastemanagement",
            r"wastegenerated",
            r"hazardouswaste",
            r"electricityconsumption",
            r"fuelconsumption",
            r"^(?:nox|sox)$",
            r"particulatematter",
            r"persistentorganicpollutants",
            r"volatileorganiccompounds",
            r"hazardousairpollutants",
            r"totalwaste",
            r"wasterecovered",
            r"wastedisposed",
            r"wasteintensity",
            r"batterywaste",
            r"biomedicalwaste",
            r"radioactivewaste",
            r"plasticwaste",
            r"constructionanddemolition",
            r"^ewaste$",
            r"performanceachieveandtrade",
            r"compliantwiththeapplicableenvironmentallaw",
            r"principle6",
        ],
    },
    7: {
        "name": "Public Policy Advocacy",
        "leadership_patterns": [
            r"publicpolicyadvocated",
            r"publicpolicyposition",
            r"methodresortedforsuchadvocacy",
            r"anticompetitive",
        ],
        "essential_patterns": [
            r"tradeandindustrychamber",
            r"affiliation.*trade",
            r"tradeassociation",
            r"principle7",
        ],
    },
    8: {
        "name": "Inclusive Growth & Equitable Development",
        "leadership_patterns": [
            r"negativesocialimpact.*mitigate",
            r"aspirationaldistrict",
            r"preferentialprocurement",
            r"intellectualpropert",
            r"traditionalknowledge",
            r"beneficiariesofcsr",
            r"percentageofbeneficiariesfromvulnerable",
            r"csrproject",
            r"benefittedfromcsr",
            r"marginalizedorvulnerablegroups.*procure",
            r"outcomeoftheinitiative",
            r"correctiveactiontakenforinitiative",
            r"initiativeundertaken",
        ],
        "essential_patterns": [
            r"socialimpactassessment",
            r"rehabilitationandresettlement",
            r"grievancesofthecommunity",
            r"communitygrievance",
            r"sourcedfromsuppliers.*local",
            r"jobcreationinsmallertowns",
            r"percentageofjobcreation",
            r"msmesorsmallproducers",
            r"withinthedistrict",
            r"principle8",
        ],
    },
    9: {
        "name": "Consumer Engagement",
        "leadership_patterns": [
            r"weblinkwhereinformationonproducts",
            r"stepstakentoinformandeducateconsumers",
            r"riskofdisruptionordiscontinuationofessentialservices",
            r"displayproductinformation",
            r"consumersatisfaction",
            r"survey.*consumer",
            r"businesscontinuityanddisaster",
        ],
        "essential_patterns": [
            r"consumercomplaint",
            r"informationabout.*environmental.*social.*risk",
            r"productrecall",
            r"forcedrecall",
            r"voluntaryrecall",
            r"productinformation.*mandated",
            r"cybersecurity",
            r"dataprivacy",
            r"databreach",
            r"deliveryofessentialservices",
            r"principle9",
        ],
    },
}

NOTES_PRINCIPLE_TAG_RE = re.compile(r"notesprinciple[1-9]explanatorytextblock")

ESSENTIAL_SPLIT_REGEX = re.compile(
    r"(?:^|\n)\s*(?:(?:For\s+)?ESSENTIAL\s+INDICATOR[S]?|EI\s*[-–:\.\d])",
    re.IGNORECASE
)
LEADERSHIP_SPLIT_REGEX = re.compile(
    r"(?:^|\n)\s*(?:(?:For\s+)?LEADERSHIP\s+INDICATOR[S]?|LI\s*[-–:\.\d])",
    re.IGNORECASE
)


# ==============================================================================
# XBRL Context and Element Parser
# ==============================================================================

@dataclass
class XBRLFact:
    tag: str
    value: str
    context_ref: str
    dimensions: list[str]
    is_narrative: bool


class BRSRXBRLExtractor:
    """
    Structured parser for SEBI BRSR XBRL instance files.
    Extracts Section C disclosures, maps them by Principle and Indicator Type,
    and formats tabular data with explicit context dimensions.
    """

    def __init__(self, xml_path: str | Path):
        self.xml_path = Path(xml_path)
        if not self.xml_path.exists():
            raise FileNotFoundError(f"XBRL file not found: {self.xml_path}")

        self.tree = ET.parse(self.xml_path)
        self.root = self.tree.getroot()
        self.contexts = self._parse_contexts()
        self.assurance_metadata = self._parse_assurance_metadata()

    def _parse_contexts(self) -> dict[str, list[str]]:
        """
        Parses all explicit dimensions and scenario members defined in XBRL contexts.
        Returns a dictionary mapping context_id -> list of descriptive dimension strings.
        """
        contexts = {}
        for el in self.root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local == "context":
                cid = el.attrib.get("id", "")
                dims = []
                for child in el.iter():
                    clocal = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if "explicitMember" in clocal:
                        # Clean member name, e.g. 'in-capmkt:MaleMember' -> 'Male'
                        raw_mem = child.text or ""
                        clean_mem = raw_mem.split(":")[-1].replace("Member", "")
                        dims.append(clean_mem)
                contexts[cid] = dims
        return contexts

    def _parse_assurance_metadata(self) -> dict[int, dict[str, str]]:
        """
        Extracts BRSR Core assurance levels for Principles 1 through 9.
        """
        assurance = {i: {"Essential": "Unknown", "Leadership": "Unknown"} for i in range(1, 10)}
        for el in self.root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            val = (el.text or "").strip()
            if not val:
                continue

            for p in range(1, 10):
                if local == f"TypeOfAssuranceForPrinciple{p}EssentialIndicators":
                    assurance[p]["Essential"] = val
                elif local == f"TypeOfAssuranceForPrinciple{p}LeadershipIndicators":
                    assurance[p]["Leadership"] = val
        return assurance

    def extract_section_c(self) -> dict[int, dict[str, str]]:
        """
        Extracts Section C disclosures partitioned by Principle (1-9)
        and Indicator Type ('Essential' vs 'Leadership').

        Returns:
            dict: {principle_number: {'Essential': text, 'Leadership': text}}
        """
        principle_elements = {
            p: {"Essential": [], "Leadership": []}
            for p in range(1, 10)
        }

        # Check for dedicated Principle Notes ExplanatoryTextBlocks
        notes_blocks = {}
        for el in self.root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            for p in range(1, 10):
                if local.lower() == f"notesprinciple{p}explanatorytextblock":
                    txt = (el.text or "").strip()
                    if txt:
                        notes_blocks[p] = txt

        # Process all facts and narrative elements in the instance document
        for el in self.root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            txt = (el.text or "").strip()
            if not txt or len(txt) == 0:
                continue

            # Only XBRL facts carry a contextRef. Elements without one (e.g. *Domain members,
            # dates, identifiers) are structural and must not be emitted as disclosures.
            if "contextRef" not in el.attrib:
                continue

            # Skip metadata and assurance declaration tags from narrative accumulation
            if any(pfx in local for pfx in ("TypeOfAssurance", "AssuranceSubType", "Whether", "NotesGeneral", "RemarksForAssurance")):
                continue

            local_lower = local.lower()

            # Principle Notes blocks are assembled separately (split by tier below);
            # emitting them here as well would duplicate them and leak Leadership text into Essential.
            if NOTES_PRINCIPLE_TAG_RE.fullmatch(local_lower):
                continue

            # Map tag to its respective Principle and Tier (Leadership vs Essential)
            matched_principle = None
            target_tier = "Essential"

            # Check leadership patterns first to prevent general keywords from absorbing voluntary disclosures
            for p, cfg in PRINCIPLE_TAXONOMY_MAP.items():
                if any(re.search(pat, local_lower) for pat in cfg["leadership_patterns"]):
                    matched_principle = p
                    target_tier = "Leadership"
                    break

            # If not matched in leadership, check essential patterns
            if matched_principle is None:
                for p, cfg in PRINCIPLE_TAXONOMY_MAP.items():
                    if any(re.search(pat, local_lower) for pat in cfg["essential_patterns"]):
                        matched_principle = p
                        target_tier = "Essential"
                        break

            if matched_principle is None:
                continue

            # Context dimensions
            cref = el.attrib.get("contextRef", "")
            dims = self.contexts.get(cref, [])
            dim_str = f"[{' | '.join(dims)}] " if dims else ""

            # Check if narrative text block or structured tabular fact
            is_narrative = (
                "textblock" in local_lower
                or "explanatory" in local_lower
                or "description" in local_lower
                or len(txt) > 80
            )

            if is_narrative:
                fact_entry = f"{local}:\n{txt}"
            else:
                fact_entry = f"{dim_str}{local}: {txt}"

            principle_elements[matched_principle][target_tier].append(fact_entry)

        # Assemble the final text blocks for each Principle
        results = {}
        for p in range(1, 10):
            results[p] = {}

            # Check if there is a master notes explanatory block for this principle
            notes_text = notes_blocks.get(p, "")
            notes_ess = ""
            notes_lead = ""

            if notes_text:
                ess_m = ESSENTIAL_SPLIT_REGEX.search(notes_text)
                lead_m = LEADERSHIP_SPLIT_REGEX.search(notes_text)

                if ess_m and lead_m and ess_m.start() < lead_m.start():
                    notes_ess = notes_text[ess_m.end():lead_m.start()].strip()
                    notes_lead = notes_text[lead_m.end():].strip()
                elif ess_m:
                    notes_ess = notes_text[ess_m.end():].strip()
                elif lead_m:
                    notes_lead = notes_text[lead_m.end():].strip()
                else:
                    notes_ess = notes_text.strip()

            for tier in ("Essential", "Leadership"):
                notes_part = notes_lead if tier == "Leadership" else notes_ess
                facts_part = "\n".join(principle_elements[p][tier])

                combined_sections = []
                if notes_part:
                    combined_sections.append(f"[Principle Notes Narrative]\n{notes_part}")
                if facts_part:
                    combined_sections.append(f"[Structured Disclosures & Facts]\n{facts_part}")

                results[p][tier] = "\n\n".join(combined_sections).strip()

        return results

    def to_brsr_rows(
        self,
        company_id: str,
        company_name: str,
        sector: str,
        fiscal_year: str,
        extraction_date: str,
        co_code: int = 0,
        fy: int = 0,
        nic_code: str = "",
        prowess_industry: str = "",
    ) -> list[BRSRRow]:
        """
        Converts the extracted Section C disclosures into validated BRSRRow instances.
        Attaches Prowess panel keys (co_code, fy) for seamless relational merging.
        """
        section_c = self.extract_section_c()
        rows = []

        for p in range(1, 10):
            for ind_type in ("Essential", "Leadership"):
                text = section_c[p].get(ind_type, "").strip()
                if not text:
                    continue

                row = BRSRRow(
                    company_id=company_id,
                    company_name=company_name,
                    sector=sector,
                    fiscal_year=fiscal_year,
                    principle_number=p,
                    indicator_type=ind_type,
                    section_text=text,
                    source_type="XBRL",
                    source_url_or_filepath=str(self.xml_path),
                    extraction_date=extraction_date,
                    extraction_method="automated",
                    co_code=co_code,
                    fy=fy,
                    nic_code=nic_code,
                    prowess_industry=prowess_industry,
                )
                rows.append(row)

        return rows


# ==============================================================================
# CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python xbrl_section_c_extractor.py path/to/filing.xml")
        sys.exit(1)

    target_xml = sys.argv[1]
    extractor = BRSRXBRLExtractor(target_xml)
    print(f"Loaded XBRL: {target_xml}")
    print(f"Total parsed contexts: {len(extractor.contexts)}")

    print("\n--- BRSR Core Assurance Metadata ---")
    for p, tiers in extractor.assurance_metadata.items():
        print(f"  Principle {p}: Essential={tiers['Essential']}, Leadership={tiers['Leadership']}")

    print("\n--- Extracted Section C Principles ---")
    disclosures = extractor.extract_section_c()
    for p in range(1, 10):
        ess_len = len(disclosures[p]["Essential"])
        lead_len = len(disclosures[p]["Leadership"])
        print(f"  Principle {p} ({PRINCIPLE_TAXONOMY_MAP[p]['name']}):")
        print(f"    Essential : {ess_len:5d} characters")
        print(f"    Leadership: {lead_len:5d} characters")
