"""
The :mod:`hotspots.result` contains classes to extract valuable information from the calculated Fragment Hotspot Maps.

The main classes of the :mod:`hotspots.result` module are:
    - :class:`hotspots.result.Results`
    - :class:`hotspots.result.Extractor`

:class:`hotspots.result.Results` can be generated using the :mod:`hotspots.calculation` module

>>> from hotspots.calculation import Runner
>>>
>>> r = Runner()

either

>>> r.from_pdb("pdb_code")

or

>>> from ccdc.protein import Protein
>>> protein = Protein.from_file("path_to_protein")
>>> result = r.from_protein(protein)

The :class:`hotspots.result.Results` is the central class for the entire API. Every module either feeds into creating
a :class:`hotspots.result.Results` instance or uses it to generate derived data structures.

The :class:`hotspots.result.Extractor` enables the main result to be broken down based on molecular volumes. This
produces molecule sized descriptions of the cavity and aids tractibility analysis and pharmacophoric generation.
"""
from __future__ import print_function, division

import copy
import operator
import pickle
from collections import OrderedDict
from os import getcwd

import numpy as np
from ccdc.cavity import Cavity
from ccdc.molecule import Molecule, Atom
from ccdc.pharmacophore import Pharmacophore
from scipy.stats import percentileofscore
from scipy.spatial import distance

from hotspots.grid_extension import Grid, _GridEnsemble

from hotspots.hs_pharmacophore import PharmacophoreModel
from hotspots.pharmacophore_extension import ProteinPharmacophoreModel

from hotspots.hs_utilities import Helper
from hotspots.protein_extension import Protein


class _Scorer(Helper):
    """
    A class to handle the annotation of objects with Fragment Hotspot Scores

    :param `hotspots.result.Results` hotspot_result: a Fragment Hotspot Map result
    :param obj: either `ccdc.molecule.Molecule` or `ccdc.protein.Protein`
    :param int tolerance: search distance
    """

    def __init__(self, hotspot_result, obj, tolerance):
        self.hotspot_result = hotspot_result
        self.object = obj
        self.tolerance = tolerance

        if isinstance(obj, Protein):
            self._scored_object = self.score_protein()

        elif isinstance(obj, Molecule):
            self._scored_object = self.score_molecule()

        elif isinstance(obj, Cavity):
            self._scored_object = self.score_cavity()

        elif not obj:
            self._scored_object = self.score_hotspot()

        else:
            raise IOError("supplied object not currently supported, soz!")

    @property
    def scored_object(self):
        return self._scored_object

    def _score_protein_cavity(self, prot):
        """
        (prefered option)
        score a protein's atoms, values stored as partial charge
        h_bond_distance between 1.5 - 2.5 A (2.0 A taken for simplicity)
        This method uses the cavity API to reduce the number of atoms to iterate over.

        :return: :class:`ccdc.protein.Protein`
        """
        feats = set([f for f in self.hotspot_result.features])
        h_bond_distance = 2.0
        interaction_pairs = {"acceptor": "donor",
                             "donor": "acceptor",
                             "pi": "apolar",
                             "aliphatic": "apolar",
                             "aromatic": "apolar",
                             "apolar": "apolar",
                             "donor_acceptor": "doneptor",
                             "dummy": "dummy"}

        cavities = Helper.cavity_from_protein(self.object)

        for cavity in cavities:
            for feature in cavity.features:
                # all cavity residues
                for atm in feature.residue.atoms:
                    if atm.is_donor is False and atm.is_acceptor is False and atm.atomic_number != 1:
                        score = self.hotspot_result.super_grids['apolar'].get_near_scores(atm.coordinates)
                        if len(score) == 0:
                            score = 0
                        else:
                            score = max(score)
                        prot.atoms[atm.index].partial_charge = score

                # polar cavity residues
                if feature.type == "acceptor" or feature.type == "donor" or feature.type == "doneptor":
                    v = feature.protein_vector
                    translate = tuple(map(h_bond_distance.__mul__, (v.x, v.y, v.z)))
                    c = feature.coordinates
                    coordinates = tuple(map(operator.add, (c.x, c.y, c.z), translate))

                    if feature.atom:
                        score = [f.score_value for f in feats if f.grid.contains_point(coordinates, tolerance=2)
                                 and f.feature_type == interaction_pairs[feature.type]]
                        if len(score) == 0:
                            score = 0
                        else:
                            score = max(score)
                            print(score)

                        prot.atoms[feature.atom.index].partial_charge = score

                        # score hydrogen atoms (important for GOLD)
                        a = [a.index for a in prot.atoms[feature.atom.index].neighbours
                             if int(a.atomic_number) == 1]
                        if len(a) > 0:
                            for atm in a:
                                prot.atoms[atm].partial_charge = score

        return prot

    def _score_protein_backup(self, prot):
        """
        backup protein scoring method to deal with cases where the cavity reader fails
        NB: this scorer is used in the GOLD Docking optimisation work


        :return:
        """

        def fetch_scores(atom, grid, tolerance=4):
            try:
                return max(self.hotspot_result.super_grids[grid].get_near_scores(coordinate=atom.coordinates,
                                                                                 tolerance=tolerance)
                           )
            except ValueError:
                return 0.0

        for residue in prot.residues:
            for atom in residue.atoms:
                # skip all hydrogens
                if atom.atomic_number == 1:
                    continue

                atom_type = self.get_atom_type(atom)

                # score donor hydrogens
                if atom_type == 'donor':
                    for n in atom.neighbours:
                        if n.atomic_number == 1:
                            n.partial_charge = fetch_scores(atom, 'acceptor', tolerance=5)

                # score donor/acceptors atoms
                elif atom_type == 'doneptor':
                    atom.partial_charge = fetch_scores(atom, 'donor', tolerance=5)
                    for n in atom.neighbours:
                        if n.atomic_number == 1:
                            n.partial_charge = fetch_scores(atom, 'acceptor', tolerance=5)

                # score remaining atoms
                elif atom_type == 'acceptor':
                    atom.partial_charge = fetch_scores(atom, 'donor', tolerance=5)

                else:
                    atom.partial_charge = fetch_scores(atom, 'donor', tolerance=4)

        return prot

    def score_protein(self):
        """
        score a protein's atoms, values stored as partial charge

        :return: :class:`ccdc.protein.Protein`
        """
        # TODO: enable cavities to be generated from Protein objects

        prot = self.object
        try:
            prot = self._score_protein_cavity(prot=prot)
            print("a")

        except IndexError:
            prot = self._score_protein_backup(prot=prot)
            print("b")

        return prot

    def score_molecule(self):
        """
        score a molecule's atoms, values stored as partial charge
        :return:
        """
        # TODO: score has been placed in partial charge field. This score will persist during read and write
        mol = copy.copy(self.object)
        for atom in mol.heavy_atoms:
            atom_type = self._atom_type(atom=atom)
            score = self._score_atom_type(atom_type, atom.coordinates)
            atom.partial_charge = score

        return mol

    @staticmethod
    def _score_feature(f):
        ideal_coord = (f.coordinates[n] + 1.8 * (f.protein_vector[n]) for n in xrange(0, 2))

    def score_cavity(self):
        # TODO: return scored cavity _features, the score protein function should be enough tbh
        cav = copy.copy(self.scored_object)

        for f in cav.features:
            self._score_feature(f)

    def score_hotspot(self, threshold=5, percentile=50):
        """
        Hotspot scored on the median value of all points included in the hotspot.
        NB: grid point with value < 5 are ommited from fragment hotspot map (hence the default threshold)
        :param percentile:
        :return:
        """
        sg = Grid.get_single_grid(self.hotspot_result.super_grids, mask=False)
        return sg.grid_score(threshold=threshold, percentile=percentile)

    def _score_atom_type(self, grid_type, coordinates):
        """
        atom
        :param grid_type:
        :param coordinate:
        :param tolerance:
        :return:
        """
        if grid_type == "doneptor":
            grid_type = self._doneptor_grid(coordinates)

        if grid_type =='no_score':
            apolar_score = self.hotspot_result.super_grids['apolar'].value_at_coordinate(coordinates,
                                                                                         tolerance=self.tolerance,
                                                                                         position=False)
            if apolar_score > 2:
                return 1
            else:
                return 0

        score =self.hotspot_result.super_grids[grid_type].value_at_coordinate(coordinates,
                                                                              tolerance=self.tolerance,
                                                                              position=False)

        return score

    def _percentage_rank(self, obj, threshold=5):
        """
        NB: must score obj first!
        :param obj:
        :param threshold:
        :return:
        """
        mol = copy.copy(self.scored_object)
        adict = {p: g.grid_values(threshold=threshold) for p, g in self.hotspot_result.super_grids.items()}

        for atom in mol.atoms:
            atom_type = self._atom_type(atom)
            if atom_type == "doneptor":
                atom_type = self._doneptor_grid(atom.coordinates)
            atom.partial_charge = percentileofscore(adict[atom_type], atom.partial_charge)

        return mol

    def _doneptor_grid(self, coordinates):
        """
        An atom is scored from the grid which yields the highest value
        :param coordinates:
        :param grid_type:
        :return:
        """
        scores = [self.hotspot_result.super_grids["donor"].value_at_coordinate(coordinates,
                                                                               tolerance=self.tolerance,
                                                                               position=False),
                  self.hotspot_result.super_grids["acceptor"].value_at_coordinate(coordinates,
                                                                                  tolerance=self.tolerance,
                                                                                  position=False)
                  ]
        d = dict(zip(scores, ["donor", "acceptor"]))
        return d[max(d.keys())]

    @staticmethod
    def _atom_type(atom):
        """
        from a ccdc Atom, the "atom type" is returned
        :param a:
        :return:
        """
        if atom.is_donor and atom.is_acceptor:
            return "doneptor"

        elif atom.is_acceptor:
            return "acceptor"

        elif atom.is_donor:
            return "donor"

        elif atom.atomic_symbol == "Xe":
            return "dummy"

        else:
            polar_neighbours = [a for a in atom.neighbours if a.is_donor or a.is_acceptor]
            if len(polar_neighbours) == 0:
                return "apolar"
            return "no_score"

class Results(Helper):
    """
    A class to handle the results of the Fragment Hotspot Map calcation and to organise subsequent analysis

    :param dict super_grids: key = probe identifier and value = grid
    :param `ccdc.protein.Protein` protein: target protein
    :param `ccdc.utilities.Grid` buriedness: the buriedness grid
    :param bool pharmacophore: if True, a pharmacophore will be generated
    """

    def __init__(self, super_grids, protein, buriedness=None, pharmacophore=None, superstar=None,
                 weighted_superstar=None, identifier=None):

        self.super_grids = super_grids
        for probe, g in super_grids.items():
            assert type(g.bounding_box) is tuple, "Not a valid Grid"

        self.protein = protein
        self.buriedness = buriedness
        self.superstar = superstar
        self.weighted_superstar = weighted_superstar
        self.pharmacophore = pharmacophore
        self._features = self._get_features(interaction_dict=super_grids)
        self.identifier = identifier

        if pharmacophore:
            self.pharmacophore = self.get_pharmacophore_model()

    class _ConstraintData(object):
        """
        standardise constrain read and write (required for the GOLD optimisation)

        """

        def __init__(self, score_by_index, prot=None):
            self.score_by_index = OrderedDict(score_by_index)
            self.protein = prot

        def to_molecule(self, protein=None):
            if self.protein is None:
                if protein is None:
                    raise AttributeError("Give me a protein")
            mol = Molecule(identifier="constraints")
            for score, index in self.score_by_index.items():
                atm = self.protein.atoms[index]
                atm.label = str(score)
                mol.add_atom(atm)
            return mol

        def write(self, path):
            f = open(path, "wb")
            pickle.dump(self.score_by_index, f)
            f.close()

        @staticmethod
        def read(path):
            f = open(path, "rb")
            d = pickle.load(f)
            f.close()
            return Results._ConstraintData(d)

    class _HotspotFeature(object):
        """
        class to hold polar islands above threshold "_features"
        purpose: enables feature ranking
        """

        def __init__(self, feature_type, grid, threshold):
            """

            :param feature_type:
            :param grid:
            :param threshold:
            """
            self._feature_type = feature_type
            self._grid = grid
            self._feature_coordinates = grid.centroid()
            self._count = (grid > 0).count_grid()
            self._threshold = threshold
            self._score_value = self.score_feature()
            self._sphere = None

            # set these
            self._rank = None
            self.superstar_results = []

        @property
        def feature_type(self):
            return self._feature_type

        @property
        def grid(self):
            return self._grid

        @property
        def feature_coordinates(self):
            return self._feature_coordinates

        @property
        def sphere(self):
            return self._sphere

        @property
        def count(self):
            return self._count

        @property
        def score_value(self):
            return self._score_value

        @property
        def rank(self):
            return self._rank

        @property
        def threshold(self):
            return self._threshold

        # def score_feature(self, threshold=14, percentile=99):
        #     """
        #     returns
        #     :return:
        #     """
        #     return self.grid.grid_score(threshold=threshold,
        #                                 percentile=percentile)
        def score_feature(self):
            """
            returns
            :return:
            """
            return self.grid.extrema[1]

    @property
    def features(self):
        return self._features

    @features.setter
    def features(self, threshold):
        self._features = self._get_features(self.super_grids, threshold=threshold)

    # def tractability_map(self):
    #     """
    #     generate the best volume and labels with the median value. A median > 14 is more likely to be tractable
    #
    #     :return: a :class:`hotspots.result.Results` instance
    #     """
    #     extractor_settings = Extractor.Settings()
    #     extractor_settings.cutoff = 5
    #     extractor_settings.island_max_size = 500
    #
    #     extractor = Extractor(self, settings=extractor_settings)
    #     extractor.extract_best_volume(volume=500)
    #     # hist = extractor.extracted_hotspots[0].map_values()
    #     #
    #     # all_points = []
    #     # for x in hist.values():
    #     #     all_points += x.flatten().tolist()
    #     #
    #     # all_points = all_points[all_points != 0]
    #     # print(all_points)
    #     best_vol = extractor.extracted_hotspots[0]
    #     best_vol.identifier = best_vol.score()
    #
    #     return best_vol
    #
    # def all_tractability_maps(self):
    #     """
    #     generate the best volume and labels with the median value. A median > 14 is more likely to be tractable
    #
    #     :return: a :class:`hotspots.result.Results` instance
    #     """
    #     extractor_settings = Extractor.Settings()
    #     extractor_settings.cutoff = 5
    #     extractor_settings.island_max_size = 500
    #
    #     extractor = Extractor(self, settings=extractor_settings)
    #     extractor.extract_all_volumes(volume=500)
    #     extracted = []
    #     for cav in extractor.extracted_hotspots:
    #         hist = cav.map_values()
    #         all_points = []
    #         for x in hist.values():
    #             all_points += x.flatten().tolist()
    #
    #         all_points = all_points[all_points != 0]
    #         best_vol = cav
    #         best_vol.identifier = np.median(all_points)
    #         extracted.append(best_vol)
    #
    #     return extracted

    def score(self, obj=None, tolerance=2):
        """
        annotate protein, molecule or self with Fragment Hotspot scores

        :param obj: `ccdc.protein.Protein`, `ccdc.molecule.Molecule` or `hotsptos.result.Results` (find the median)
        :param int tolerance: the search radius around each point
        :return: scored obj, either :class:`ccdc.protein.Protein`, :class:`ccdc.molecule.Molecule` or :class:`hotspot.result.Results`

        >>> result          # example "1hcl"
        <hotspots.result.Results object at 0x000000001B657940>

        >>> from numpy import np
        >>> p = result.score(result.protein)    # scored protein
        >>> np.median([a.partial_charge for a in p.atoms if a.partial_charge > 0])
        8.852499961853027
        """
        return _Scorer(self, obj, tolerance).scored_object

    def _filter_map(self, g1, g2, tol):
        """
        *Experimental feature*

        Takes 2 grids of the same size and coordinate frames. Points that are
        zero in one grid but sampled in the other are
        set to the mean of their nonzero neighbours. Grids are then subtracted and
        the result is returned.

        :param int tol: how many grid points away to consider scores from
        :param g1: a :class: "ccdc.utilities.Grid" instance
        :param g2: a :class: "ccdc.utilities.Grid" instance
        :return: a :class: "ccdc.utilities.Grid" instance
        """

        def filter_point(x, y, z):
            loc_arr = np.array(
                [g[x + i][y + j][z + k] for i in range(-tol, tol + 1) for j in range(-tol, tol + 1) for k in
                 range(-tol, tol + 1)])
            if loc_arr[loc_arr > 0].size != 0:
                # print(np.mean(loc_arr[loc_arr > 0]))
                new_grid[x][y][z] = np.mean(loc_arr[loc_arr > 0])

        vfilter_point = np.vectorize(filter_point)
        com_bound_box = g1.bounding_box
        com_spacing = g1.spacing

        arr1 = g1.get_array()
        arr2 = g2.get_array()

        b_arr1 = np.copy(arr1)
        b_arr2 = np.copy(arr2)

        b_arr1[b_arr1 > 0] = 1.0
        b_arr2[b_arr2 > 0] = -1.0

        diff_arr = b_arr1 + b_arr2

        unmatch1 = np.where(diff_arr == 1)
        unmatch2 = np.where(diff_arr == -1)

        g = arr1
        new_grid = np.copy(arr1)
        vfilter_point(unmatch2[0], unmatch2[1], unmatch2[2])
        f_arr1 = np.copy(new_grid)

        g = arr2
        new_grid = np.copy(arr2)
        vfilter_point(unmatch1[0], unmatch1[1], unmatch1[2])
        f_arr2 = np.copy(new_grid)

        sel_arr = f_arr1 - f_arr2
        sel_arr[sel_arr < 0] = 0
        sel_map = Grid(origin=com_bound_box[0], far_corner=com_bound_box[1], spacing=com_spacing, _grid=None)

        idxs = sel_arr.nonzero()
        vals = sel_arr[idxs]

        as_triads = zip(*idxs)
        for (i, j, k), v in zip(as_triads, vals):
            sel_map._grid.set_value(int(i), int(j), int(k), v)

        return sel_map

    def get_difference_map(self, other, tolerance):
        """
        *Experimental feature.*
        Generates maps to highlight selectivity for a target over an off target cavity. Proteins should be aligned
        by the binding site of interest prior to calculation.
        High scoring regions of a map represent areas of favourable interaction in the target binding site, not
        present in off target binding site

        :param other: a :class:`hotspots.result.Results` instance
        :param int tolerance: how many grid points away to apply filter to
        :return: a :class:`hotspots.result.Results` instance
        """

        selectivity_grids = {}
        for probe in self.super_grids.keys():
            g1 = self.super_grids[probe]
            g2 = other.super_grids[probe]
            og1, og2 = Grid.common_grid([g1, g2])
            sele = self._filter_map(og1, og2, tolerance)
            selectivity_grids[probe] = sele
        hr = Results(selectivity_grids, self.protein, None, None)
        return hr

    @staticmethod
    def from_grid_ensembles(res_list, prot_name, charged=False, mode='max'):
        """
        *Experimental feature*

        Creates ensemble map from a list of Results. Structures in the ensemble have to aligned by the
        binding site of interest prior to the hotspots calculation.

        TODO: Move to the calculation module?

        :param res_list: list of `hotspots.result.Results`
        :param str prot_name: str
        :param str out_dir: path to output directory
        :return: a :class:`hotspots.result.Results` instance
        """
        if charged:
            probe_list = ["acceptor", "apolar", "donor", "positive", "negative"]
        else:
            probe_list = ["acceptor", "apolar", "donor"]

        grid_dic = {}

        for p in probe_list:
            grid_list_p = [r.super_grids[p].minimal() for r in res_list]
            ens = _GridEnsemble()
            grid_dic[p] = ens.from_grid_list(grid_list_p, getcwd(), prot_name, p, mode=mode)

        hr = Results(grid_dic, protein=res_list[0].protein)
        return hr

    def get_pharmacophore_model(self, identifier="id_01", threshold=5):
        """
        Generates a :class:`hotspots.hotspot_pharmacophore.PharmacophoreModel` instance from peaks in the hotspot maps

        TODO: investigate using feature recognition to go from grids to features.

        :param str identifier: Identifier for displaying multiple models at once
        :param float cutoff: The score cutoff used to identify islands in the maps. One peak will be identified per island
        :return: a :class:`hotspots.hotspot_pharmacophore.PharmacophoreModel` instance
        """
        return PharmacophoreModel.from_hotspot(self, identifier=identifier, threshold=threshold)

    def grid_labels(self):
        """
        Detect local maxima and generate a dict of peak by value

        :return: Peak coordinates by peak values.
        :rtype: dict
        """
        labels = {}
        for p, g in self.super_grids.items():
            h = g.max_value_of_neighbours()
            h = h.gaussian()
            # take the original grid value, grid modifications for peak
            # detection purposes only, not to augment the HS values
            labels.update({p: {peak: g.value_at_point(peak) for peak in h.get_peaks(min_distance=1, cutoff=5)}})

        return labels

    def atomic_volume_overlap(self, mol):
        """
        for a given mol, return a dictionary of dictionaries containing the percentage overlap of each atoms
        VDW radius with the Hotspot Grids.

        {"donor": {"atomic_label": percentage_overlap}

        :param mol:
        :return:
        """

        atom_type_dic = {}
        for n, g in self.super_grids.items():
            # if an atom is a donor and acceptor consider overlap twice
            atms = [a for a in mol.heavy_atoms
                    if self.get_atom_type(a) == n
                    or ((n == 'donor' or n == 'acceptor') and self.get_atom_type(a) == 'doneptor')]

            if len(atms) > 0:
                overlap_dic = {a.label: g.atomic_overlap(atom=a, return_grid=False) for a in atms}
                atom_type_dic.update({n: overlap_dic})
        print(str(atom_type_dic))
        return atom_type_dic

    def percentage_matched_atoms(self, mol, threshold, match_atom_types=True):
        """
        for a given molecule, the 'percentage match' is given by the percentage of atoms
        which overlap with the hotspot result (over a given overlap threshol)

        :param mol:
        :param threshold:
        :param match_atom_types:
        :return:
        """
        matched_atom_count = 0
        if match_atom_types:
            atom_type_dic = {}
            for n, g in self.super_grids.items():
                # if an atom is a donor and acceptor consider overlap twice
                atms = [a for a in mol.heavy_atoms if self.get_atom_type(a) == n
                        or ((n == 'donor' or n == 'acceptor') and self.get_atom_type(a) == 'doneptor')]

                if len(atms) > 0:

                    matched = g.matched_atoms(atoms=atms, threshold=threshold)
                    matched_atom_count += len(matched)
                    atom_type_dic.update({n: matched})

            print("heavy atoms matched: {}/{}".format(matched_atom_count, len(mol.heavy_atoms)))
            print("breakdown by atom type", str(atom_type_dic))
            return round((matched_atom_count / len(mol.heavy_atoms)) * 100, 1), atom_type_dic
        else:
            sg = Grid.get_single_grid(self.super_grids, mask=False)
            matched = sg.matched_atoms(atoms=mol.heavy_atoms, threshold=threshold)
            matched_atom_count += len(matched)

            print("heavy atoms matched: {}/{}".format(matched_atom_count, len(mol.heavy_atoms)))
            return round((matched_atom_count / len(mol.heavy_atoms)) * 100, 1)

    @staticmethod
    def _is_solvent_accessible(protein_coords, atm, min_distance=2):
        """
        given a protein and an atom of a protein, determine if the atom is accessible to solvent
        :param protein:
        :param atm:
        :return:
        """
        if str(atm.atomic_symbol) == 'H':
            atm_position = np.array(atm.coordinates)
            neighbour = np.array(atm.neighbours[0].coordinates)
            direction = np.subtract(atm_position, neighbour) * 2
            position = np.array([direction + atm_position])
            distance = min(np.linalg.norm(protein_coords - position, axis=1))
            if distance > min_distance:
                return True
            else:
                return False

        else:
            return True

    def _docking_fitting_pts(self, _best_island=None, threshold=17):
        """

        :return:
        """
        if _best_island:
            single_grid = _best_island
        else:
            single_grid = Grid.get_single_grid(self.super_grids, mask=False)
        dic = single_grid.grid_value_by_coordinates(threshold=threshold)

        mol = Molecule(identifier="constraints")
        for score, v in dic.items():
            for pts in v:
                atm = Atom(atomic_symbol='C',
                           atomic_number=14,
                           label='{:.2f}'.format(score),
                           coordinates=pts)
                atm.partial_charge = score
                mol.add_atom(atom=atm)
        return mol

    def _output_feature_centroid(self):
        dic = {"apolar": "C",
               "acceptor": "N",
               "donor": "O"}
        mol = Molecule(identifier="centroids")
        for i, feat in enumerate(self.features):
            coords = feat.grid.centroid()
            mol.add_atom(Atom(atomic_symbol=dic[feat.feature_type],
                              atomic_number=14,
                              coordinates=coords,
                              label=str(i)))
        from ccdc import io
        with io.MoleculeWriter("cenroid.mol2") as w:
            w.write(mol)

    def _docking_constraint_atoms(self, p=None, max_constraints=10, accessible_cutoff=0.001, max_distance=4, threshold=14, min_size = 15):
        """
        creates a dictionary of constraints

        :param int max_constraints: max number of constraints
        :return dic: score by atom
        """

        from scipy.spatial import distance

        def check_hydrogens(protein):
            """check hydrogens have neighbours"""
            if 0 in set([len(a.neighbours) for a in protein.atoms if a.atomic_number == 1]):
                print("WARNING HYDROGENS READDED THIS MAY CAUSE ISSUES")
                protein.add_hydrogens()

        print(len(self.protein.atoms))

        if p is None:
            check_hydrogens(self.protein)
            protein = self.protein.copy()
        else:
            check_hydrogens(p)
            protein = p.copy()

        point = self.super_grids['apolar'].centroid()
        bs = protein.BindingSiteFromPoint(protein=protein, origin=point, distance=12.)

        for a in protein.atoms:
            a.label = str(a.index)

        remove = set(protein.residues) - set(bs.residues)

        for r in remove:
            protein.remove_residue(r.identifier)

        print(len(self.protein.atoms))

        donors = {x.coordinates: x.label for x in [a for a in protein.atoms if a.atomic_number == 1]
                  if x.neighbours[0].is_donor 
                  # and x.solvent_accessible_surface() > accessible_cutoff
                  }

        acceptors = {a.coordinates: a.label for a in protein.atoms
                     if a.is_acceptor
                     # and a.solvent_accessible_surface() > accessible_cutoff
                     }

        pairs = {"acceptor": donors,
                 "donor": acceptors}

        constraint_dic = {}

        for feature in self.features:
            if (feature.grid > threshold).count_grid() > min_size:
                centoid = [feature.grid.centroid()]
                coords = list(pairs[feature.feature_type].keys())
                all_distances = distance.cdist(coords, centoid, 'euclidean')
                ind = int(np.argmin(all_distances))
                min_coord = coords[ind]

                atm_index = int(pairs[feature.feature_type][min_coord])

                if all_distances[ind] < max_distance:
                    constraint_dic.update({feature.score_value: atm_index})

        if len(constraint_dic) > max_constraints:
            scores = sorted([f[0] for f in constraint_dic.items()], reverse=True)[:max_constraints]
        else:
            scores = sorted([f[0] for f in constraint_dic.items()], reverse=True)

        bin_keys = set(constraint_dic.keys()) - set(scores)
        for b in bin_keys:
            del constraint_dic[b]

        constraint_dic = OrderedDict(reversed(list(constraint_dic.items())))

        return self._ConstraintData(constraint_dic, self.protein)

    def _usr_moment(self, threshold=14):
        """
        PRIVATE
        This is some experimental code and requires seperate installation of USR
        generates USR moments for shape analysis
        :return:
        """
        try:
            from hs_utilities import _generate_usr_moment

            coords_list = [np.array(g.coordinates(threshold=threshold))
                           for p, g in self.super_grids.items()
                           if p != "negative" and p != "positive"]

            return _generate_usr_moment(fcoords_list=coords_list)

        except ImportError:
            print("To use this feature you must have USR installed")

    def map_values(self):
        """
        get the number zero grid points for the Fragment Hotspot Result

        :return: dict of str(probe type) by a :class:`numpy.array` (non-zero grid point scores)
        """
        return {p: g.get_array() for p, g in self.super_grids.items()}

    @staticmethod
    def _get_features(interaction_dict, threshold=5, min_feature_gp=6, excluded=("apolar")):
        """
        returns Hotspot Feature object with a score to enable ranking
        :param probe:
        :param g:
        :return:
        """
        f = []
        for probe, g in interaction_dict.items():
            if len(g.islands(threshold=threshold)) > 0:
                for island in g.islands(threshold=threshold):
                    if (island > threshold).count_grid() > min_feature_gp and probe not in excluded:

                        f.append(Results._HotspotFeature(probe, island, threshold))
        return f

    def _rank_features(self):
        """
        rank _features based upon feature score (TO DO: modify score if required)
        :return:
        """
        feature_by_score = {feat.score_value: feat for feat in self.features}
        score = sorted([f[0] for f in feature_by_score.items()], reverse=True)
        for i, key in enumerate(score):
            feature_by_score[key]._rank = int(i + 1)


    ############################################################################################

    # TODO: Tidy up
    def _percentile_grid(self, x):
        return percentileofscore(self.single_array,x, kind='mean')

    def normalize_to_percentile(self):
        for probe, g in self.super_grids.items():
            g_array = g.get_array()
            out_array = np.vectorize(self._percentile_grid)(g_array)

            self.super_grids[probe] = Grid.array_to_grid(out_array, g)

    def normalize_to_max(self):

        max_score = 0
        for probe, g in self.super_grids.items():
            g_max = g.extrema[1]
            if g_max > max_score:
                max_score = g_max

        for probe, g in self.super_grids.items():
            g *= 100/max_score
            self.super_grids[probe] = g
    # to grid_extension?
    ############################################################################################

    def set_background(self, background_value=1.0):

        prot_g = Grid.from_molecule(self.protein, value=background_value, scaling_type='none', scaling=1)

        for probe, g in self.super_grids.items():
            common_prot, common_g = Grid.common_grid([prot_g, g])
            bg_mask =  (common_prot <0.1) & (common_g <1)
            tmp_g = common_g + bg_mask
            new_g = tmp_g - (common_prot)
            origin, corner = g.bounding_box
            i,j,k = new_g.point_to_indices(origin)
            l,m,n = new_g.point_to_indices(corner)
            self.super_grids[probe]= new_g.sub_grid((i,j,k,l,m,n))

    @staticmethod
    def _molecule_as_grid(mol, g=None):
        """
        Produces a grid representation of a molecule split by interaction type

        :param mol: takes any ccdc molecule
        :type mol: `ccdc.molecule.Molecule`
        :param g: a blank grid
        :type g: `hotspots.grid_extension.Grid`

        :return: a dictionary of grids by interaction type
        :rtype: dict
        """

        if g is None:
            g = Grid.initalise_grid(coords=[a.coordinates for a in mol.atoms],
                                    padding=1)

        grid_dict = {"donor": g.copy(),
                     "acceptor": g.copy(),
                     "apolar": g.copy()}

        for p, g in grid_dict.items():
            if p == "acceptor":
                atms = [a for a in mol.atoms if Helper.get_atom_type(a) == p and
                        'H' not in [n.label for n in a.neighbours]]
            else:
                atms = [a for a in mol.atoms if Helper.get_atom_type(a) == p]

            for atm in atms:
                g.set_sphere(point=atm.coordinates,
                             radius=atm.vdw_radius,
                             value=1,
                             scaling='None')

        return grid_dict

    def _shrink_to_common(self, g1,g2):
        origin, corner = g1.bounding_box
        i, j, k = g2.point_to_indices(origin)
        l, m, n = g2.point_to_indices(corner)
        return g2.sub_grid((i, j, k, l, m, n))

    def score_atoms_as_spheres(self, mol):
        """
        An example of a more complex scoring scheme

        :param mol: takes any ccdc molecule
        :type mol: `ccdc.molecule.Molecule`
        :param grid: grid with the desired output dimensions
        :type grid: `ccdc.utilities.Grid`
        :return:
        """
        mol_grids = self._molecule_as_grid(mol)

        # take into account atoms which 'clash' / 'don't match' with the hotspot maps
        bad_interaction_dict = {'apolar': ['acceptor', 'donor'],
                                'donor': ['acceptor', 'apolar'],
                                'acceptor': ['donor', 'apolar']}


        sub_grids = {p: self._shrink_to_common(mol_grids[p], self.super_grids[p]) for p in mol_grids.keys()}

        scores_by_type = {}
        for probe in sub_grids.keys():
            # detemine clashes by atom type
            clash_g = (sub_grids[probe] < 0) * mol_grids[probe]
            clash_array = clash_g.get_array()
            scores_by_type[f"{probe}_clash"] = np.sum(clash_array)

            # overlap between the maps and the molecule X 2
            match_grid = (sub_grids[probe] > 0) * sub_grids[probe] * mol_grids[probe] * 2
            # match_grid.write(f"{probe}_match.grd")

            # non-match
            non_match_grids = [sub_grids[p] * (sub_grids[p] > 0) * mol_grids[probe]
                               for p in sub_grids.keys()
                               if p in bad_interaction_dict[probe]]

            non_match_g = non_match_grids[0] + non_match_grids[1]
            # non_match_g.write(f"{probe}_nonmatch.grd")

            # the score is the difference between matches and non-matches
            score_g = match_grid - non_match_g
            # score_g.write(f"{probe}_overall.grd")

            score_array = score_g.get_array()
            non_zero = score_array[score_array != 0]

            if len(non_zero) > 0:
                score = np.mean(non_zero)
            else:
                # if the len of non-zeros is 0, there will be a runtime error
                score = 0

            scores_by_type[probe] = score

        return scores_by_type

    ############################################################################################


    def common_hotspots(self, other):
        common_hotspot_grids = {}
        for probe, g in self.super_grids.items():
            common_self_g, common_other_g = Grid.common_grid(g, other.super_grids[probe])
            common_hotspot_grids[probe] = common_self_g * common_other_g

        return Results(super_grids=common_hotspot_grids, protein=self.protein, buriedness=self.buriedness)

    def single_grid_result(self):

        _masked_dic, _single_grid = Grid.get_single_grid(self.super_grids)

        grid_dict = _single_grid.inverse_single_grid(_masked_dic)
        self.super_grids = grid_dict


class Extractor(object):
    """
    A class to handle the extraction of molecular volumes from a Fragment Hotspot Map result

    :param `hotspots.HotspotResults` hr: A Fragment Hotspot Maps result
    :param `hotspots.Extractor.Settings` settings: Extractor settings
    """

    class Settings(object):
        """
        Default settings for hotspot extraction

        :param float volume: required volume (default = 150)
        :param float cutoff: only features above this value are considered (default = 14)
        :param float spacing: grid spacing, (default = 0.5)
        :param bool mvon: Run Max value of neighbours (default = True)

        """

        def __init__(self, volume=150, cutoff=14, spacing=0.5):
            self.volume = volume
            self.cutoff = cutoff
            self.spacing = spacing

        @property
        def _num_gp(self):
            """
            number of grid point for a given volume
            :return:
            """
            return int(float(self.volume) / self.spacing ** 3)

    def __init__(self, hr, settings=None):
        if settings is None:
            self.settings = self.Settings()
        else:
            self.settings = settings
        self._single_grid = None
        self._masked_dic = None
        self.out_dir = None
        self.extracted_hotspots = None
        self.threshold = None

        try:
            hr.super_grids["negative"] = hr.super_grids["negative"].deduplicate(hr.super_grids["acceptor"],
                                                                                threshold=10,
                                                                                tolerance=2)

            hr.super_grids["positive"] = hr.super_grids["positive"].deduplicate(hr.super_grids["donor"],
                                                                                threshold=10,
                                                                                tolerance=2)
        except KeyError:
            pass

        self.hotspot_result = hr
        self._masked_dic, self._single_grid = Grid.get_single_grid(self.hotspot_result.super_grids)

    @property
    def single_grid(self):
        return self._single_grid

    @property
    def masked_dic(self):
        return self._masked_dic

    def _remove_protein_vol(self, g):
        """


        :param g:
        :return:
        """
        prot_g = Grid.from_molecule(self.hotspot_result.protein,
                                    value=1,
                                    scaling_type='none',
                                    scaling=1)
        common_prot, common_g = Grid.common_grid([prot_g, g])
        new_g = common_g * (common_prot < 1)
        origin, corner = g.bounding_box
        i, j, k = new_g.point_to_indices(origin)
        l, m, n = new_g.point_to_indices(corner)

        return new_g.sub_grid((i, j, k, l, m, n))

    def _grow(self):
        """
        A single grid is iteratively inflated, and the top 20% of neighbouring grid points added until the volume
        is with the tolerance of the target volume.

        :param float tolerance: allowable error in volume extraction
        :return float: threshold
        """

        self.best_island = self._single_grid.common_boundaries(self.best_island)
        self.second_best_island = self._single_grid.common_boundaries(self.second_best_island)
        current_num_gp = self.best_island.count_grid()

        f = 0
        for f in range(0,10):
            if self.settings._num_gp <= current_num_gp:
                break
            grown = Grid.grow(self.best_island, self.second_best_island)
            self.best_island = self._remove_protein_vol(grown)
            old_num_gp = current_num_gp

            current_num_gp = self.best_island.count_grid()
            print(current_num_gp, 'out of', self.settings._num_gp)
            growth = current_num_gp - old_num_gp
            if growth == 0:
                break

        tmp_best_island = (self.best_island > 0.5) * (self._single_grid )
        g_vals = tmp_best_island.grid_values()
        g_vals[::-1].sort()
        print(len(g_vals))
        print(self.settings._num_gp)

        try:
            threshold = g_vals[self.settings._num_gp]
        except IndexError:
            threshold = min(g_vals)

        return threshold

    def _step_down(self, start_threshold):
        """
        Returns the maximum threshold for which the "best island" volume is smaller than the target volume

        :param float start_threshold: island threshold
        :return float: threhold
        """
        for threshold in range(int(start_threshold * 2), 0, -1):
            threshold *= 0.1
            self.best_island = self._single_grid.get_best_island(threshold)
            if self.best_island is not None:
                self.best_island = self.best_island.remove_small_objects(min_size=0.5*float(self.settings._num_gp))

            if self.best_island is not None and self.best_island.count_grid() > self.settings._num_gp:
                self.second_best_island = self._single_grid.get_best_island(threshold)
                threshold += 0.1
                break

        self.best_island = self.single_grid.get_best_island(threshold)

        return threshold

    def extract_volume(self, volume="125"):
        """
        Returns a HotspotResult with a restricted volume


        :param int volume: target map volume
        :return `hotspots.result.Results`: A fresh result object
        """
        self.settings.volume = volume

        assert self.single_grid.count_grid() >= self.settings._num_gp

        self.threshold = self._step_down(200)
        self.best_island = self.best_island.remove_small_objects(min_size=0.5*float(self.settings._num_gp))

        try:
            self.second_best_island = self.second_best_island.remove_small_objects(min_size=0.5*float(self.settings._num_gp))
        except AttributeError:
            self.second_best_island = self.single_grid.remove_small_objects(
                min_size=0.5 * float(self.settings._num_gp))
        self.threshold = self._grow()

        print("Final score threshold is: {} ".format(self.threshold))

        grid_dict = self.best_island.inverse_single_grid(self._masked_dic)
        return Results(super_grids=grid_dict, protein=self.hotspot_result.protein)
