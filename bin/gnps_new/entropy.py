"""
This file contains code modified from the matchms project and MSEntropy project
(https://github.com/matchms/matchms)
Copyright matchms Team 2020

(https://github.com/YuanyueLi/MSEntropy)
Copyright Yuanyue Li 2023

Modified by Shipei Xing in 2024

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import numpy as np
import numba as nb
from typing import Tuple


@nb.njit
def find_matches(ref_spec_mz: np.ndarray, qry_spec_mz: np.ndarray,
                tolerance: float, shift: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Find matching peaks between two spectra."""
    matches_idx1 = np.empty(min(len(ref_spec_mz), len(qry_spec_mz)), dtype=np.int32)
    matches_idx2 = np.empty_like(matches_idx1)
    match_count = 0
    lowest_idx = 0

    for peak1_idx in range(len(ref_spec_mz)):
        mz = ref_spec_mz[peak1_idx]
        low_bound = mz - tolerance
        high_bound = mz + tolerance

        for peak2_idx in range(lowest_idx, len(qry_spec_mz)):
            mz2 = qry_spec_mz[peak2_idx] + shift
            if mz2 > high_bound:
                break
            if mz2 < low_bound:
                lowest_idx = peak2_idx
            else:
                matches_idx1[match_count] = peak1_idx
                matches_idx2[match_count] = peak2_idx
                match_count += 1

    return matches_idx1[:match_count], matches_idx2[:match_count]


@nb.njit
def collect_peak_pairs(ref_spec: np.ndarray, qry_spec: np.ndarray, min_matched_peak: int,
                       tolerance: float, shift: float = 0.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Find and score matching peak pairs between spectra."""
    if len(ref_spec) == 0 or len(qry_spec) == 0:
        return np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)

    # No need to copy arrays since we're only reading values
    matches_idx1, matches_idx2 = find_matches(ref_spec[:, 0], qry_spec[:, 0], tolerance, shift)

    if len(matches_idx1) < min_matched_peak:
        return np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)

    # Calculate scores for matches
    scores = ref_spec[matches_idx1, 1] * qry_spec[matches_idx2, 1]

    # Sort by score descending
    sort_idx = np.argsort(-scores)
    return matches_idx1[sort_idx], matches_idx2[sort_idx], scores[sort_idx]


@nb.njit
def score_matches(matches_idx1: np.ndarray, matches_idx2: np.ndarray,
                  scores: np.ndarray, ref_spec: np.ndarray,
                  qry_spec: np.ndarray, reverse: bool) -> Tuple[float, int]:
    """Calculate entropy similarity score from matching peaks."""

    # Apply weight to intensity
    ref_spec = apply_weight_to_intensity(ref_spec)
    qry_spec = apply_weight_to_intensity(qry_spec)

    # Use boolean arrays for tracking used peaks
    used1 = np.zeros(len(ref_spec), dtype=nb.boolean)
    used2 = np.zeros(len(qry_spec), dtype=nb.boolean)

    # Initialize arrays for matched intensities
    matched_a_intensities = np.empty(len(matches_idx1), dtype=np.float32)
    matched_b_intensities = np.empty(len(matches_idx1), dtype=np.float32)

    used_matches = 0

    # Find best non-overlapping matches
    for i in range(len(matches_idx1)):
        idx1 = matches_idx1[i]
        idx2 = matches_idx2[i]
        if not used1[idx1] and not used2[idx2]:
            matched_a_intensities[used_matches] = ref_spec[idx1, 1]
            matched_b_intensities[used_matches] = qry_spec[idx2, 1]
            used1[idx1] = True
            used2[idx2] = True
            used_matches += 1

    if used_matches == 0:
        return 0.0, 0

    # Trim arrays to used matches only
    matched_a_intensities = matched_a_intensities[:used_matches]
    matched_b_intensities = matched_b_intensities[:used_matches]

    # Normalize intensities
    sum_a = np.sum(ref_spec[:, 1])
    if reverse:
        sum_b = np.sum(matched_b_intensities)
    else:
        sum_b = np.sum(qry_spec[:, 1])

    if sum_a <= 0 or sum_b <= 0:
        return 0.0, used_matches

    matched_a_intensities /= sum_a
    matched_b_intensities /= sum_b

    # Calculate entropy similarity
    peak_ab_intensities = matched_a_intensities + matched_b_intensities
    entropy_sim = 0.0

    for i in range(used_matches):
        # Calculate joint entropy term
        if peak_ab_intensities[i] > 0:
            entropy_sim += peak_ab_intensities[i] * np.log2(peak_ab_intensities[i])

        # Subtract individual entropy terms
        if matched_a_intensities[i] > 0:
            entropy_sim -= matched_a_intensities[i] * np.log2(matched_a_intensities[i])

        if matched_b_intensities[i] > 0:
            entropy_sim -= matched_b_intensities[i] * np.log2(matched_b_intensities[i])

    entropy_sim /= 2
    return min(float(entropy_sim), 1.0), used_matches


@nb.njit
def apply_weight_to_intensity(peaks: np.ndarray) -> np.ndarray:
    """Apply a weight to the intensity of a spectrum based on spectral entropy."""
    if peaks.size == 0:
        return np.zeros((0, 2), dtype=np.float32)

    # normalize intensity
    peak_sum = np.sum(peaks[:, 1])
    if peak_sum <= 0:
        return peaks

    # Make a copy of peaks to avoid modifying the input
    weighted_peaks = peaks.copy()
    weighted_peaks[:, 1] /= peak_sum

    # Calculate the spectral entropy
    valid_intensities = weighted_peaks[:, 1] > 0
    entropy = -np.sum(weighted_peaks[valid_intensities, 1] *
                     np.log(weighted_peaks[valid_intensities, 1]))

    # Apply the weight if entropy is below threshold
    if entropy < 3:
        weight = 0.25 + 0.25 * entropy
        weighted_peaks[:, 1] = np.power(weighted_peaks[:, 1], weight)
        intensity_sum = np.sum(weighted_peaks[:, 1])
        if intensity_sum > 0:
            weighted_peaks[:, 1] /= intensity_sum

    return weighted_peaks


class EntropyGreedy:
    """Calculate entropy similarity between mass spectra."""

    def __init__(self, tolerance: float = 0.1, reverse: bool = False):
        """Initialize with given parameters."""
        self.tolerance = np.float32(tolerance)
        self.reverse = reverse

    def pair(self, qry_spec, ref_spec,
             min_matched_peak: int = 1,
             analog_search: bool = False,
             shift: float = 0.0) -> Tuple[float, int]:
        """Calculate similarity between two spectra."""
        # Handle empty inputs
        if qry_spec is None or ref_spec is None:
            return 0.0, 0

        try:
            # Convert to float32 for memory efficiency
            qry_spec = np.asarray(qry_spec, dtype=np.float32)
            ref_spec = np.asarray(ref_spec, dtype=np.float32)

            if qry_spec.size == 0 or ref_spec.size == 0:
                return 0.0, 0

            if qry_spec.ndim == 1:
                qry_spec = qry_spec.reshape(-1, 2)
            if ref_spec.ndim == 1:
                ref_spec = ref_spec.reshape(-1, 2)
        except:
            return 0.0, 0

        matches_idx1, matches_idx2, scores = collect_peak_pairs(
            ref_spec, qry_spec, min_matched_peak,
            self.tolerance, shift
        )

        if len(matches_idx1) == 0:
            return 0.0, 0

        return score_matches(
            matches_idx1, matches_idx2, scores,
            ref_spec, qry_spec, self.reverse
        )


if __name__ == "__main__":
    spectrum_1 = np.array([[69, 8.0], [86, 100.0], [99, 50.0]], dtype=np.float32)

    spectrum_2 = np.array([[41, 38.0], [69, 66.0], [86, 999.0]], dtype=np.float32)

    # Example with reverse=False (forward entropy)
    entropy_standard = EntropyGreedy(tolerance=0.05, reverse=False)
    score_standard, n_matches_standard = entropy_standard.pair(spectrum_1, spectrum_2)
    print(f"Standard Score: {score_standard:.3f}, Matches: {n_matches_standard}")

    # Example with reverse=True (reverse entropy)
    entropy_reverse = EntropyGreedy(tolerance=0.05, reverse=True)
    score_reverse, n_matches_reverse = entropy_reverse.pair(spectrum_1, spectrum_2)
    print(f"Reverse Score: {score_reverse:.3f}, Matches: {n_matches_reverse}")