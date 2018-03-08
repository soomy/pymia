import abc
import typing as t

import numpy as np

from miapy.data import subjectfile as subj
from . import callback as cb
from . import fileloader as load
import miapy.data.transformation as tfm


class Traverser(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def traverse(self, files: list, loader: load.Loader, callbacks: t.List[cb.Callback]=None,
                 transform: tfm.Transform=None):
        pass


def default_concat(data: t.List[np.ndarray]) -> np.ndarray:
    if len(data) == 1:
        return data[0]
    return np.stack(data, axis=-1)


class SubjectFileTraverser(Traverser):
    def traverse(self, files: t.List[subj.SubjectFile], loader=load.SitkLoader(), callback: cb.Callback=None,
                 transform: tfm.Transform=None, concat_fn=default_concat):
        if len(files) == 0:
            raise ValueError('No files')
        if not isinstance(files[0], subj.SubjectFile):
            raise ValueError('files must be of type SubjectFile')

        subject_files = files  # only for better readability

        # getting the sequence and gt names
        sequence_names = self._get_sequence_names(subject_files)
        sequence_to_index = {name: i for i, name in enumerate(sequence_names)}

        gt_names = self._get_gt_names(subject_files)
        has_gt = len(gt_names) > 0
        callback_params = {'subject_files': subject_files, 'has_gt': has_gt, 'sequence_names': sequence_names}

        if has_gt:
            gt_to_index = {name: i for i, name in enumerate(gt_names)}
            callback_params['gt_names'] = gt_names

        if callback:
            callback.on_start(callback_params)

        # looping over the subject files and calling callbacks
        for subject_index, subject_file in enumerate(subject_files):

            callback_subject_params = {'subject': subject_file.subject, 'subject_index': subject_index}
            if callback:
                callback.on_subject_start({**callback_params, **callback_subject_params})

            subject_sequences = len(sequence_to_index)*[None]  # type: t.List[np.ndarray]
            for sequence, sequence_file in subject_file.get_sequences().items():
                seq_image = loader.load_image(sequence_file, sequence)
                np_seq_image = loader.get_ndarray(seq_image)
                subject_sequences[sequence_to_index[sequence]] = np_seq_image

                callback_image_params = {'sequence': sequence, 'sequence_index': sequence_to_index[sequence],
                                         'file': sequence_file, 'raw_image': seq_image}
                if callback:
                    callback.on_image_file({**callback_params, **callback_subject_params, **callback_image_params})

            np_sequences = concat_fn(subject_sequences)
            transform_params = {**callback_subject_params, 'images': np_sequences}

            if has_gt:
                subject_gts = len(gt_to_index) * [None]  # type: t.List[np.ndarray]
                for gt, gt_file in subject_file.label_images.items():
                    gt_image = loader.load_image_labels(gt_file, gt)
                    subject_gts[gt_to_index[gt]] = loader.get_ndarray(gt_image)

                    callback_image_params = {'gt': gt, 'gt_index': gt_to_index[gt], 'file': gt_file,
                                             'raw_label': gt_image}
                    if callback:
                        callback.on_gt_file({**callback_params, **callback_subject_params, **callback_image_params})

                np_gts = concat_fn(subject_gts)
                transform_params['labels'] = np_gts

            if transform:
                transform_params = transform(transform_params)

            if callback:
                callback.on_subject_end({**callback_params, **callback_subject_params, **transform_params})

        if callback:
            callback.on_end(callback_params)

    @staticmethod
    def _get_sequence_names(subject_files: t.List[subj.SubjectFile]) -> list:
            sequences = subject_files[0].images.keys()
            if not all(s.images.keys() == sequences for s in subject_files):
                raise ValueError('inconsistent sequence names in the subject list')
            return list(sequences)

    @staticmethod
    def _get_gt_names(subject_files: t.List[subj.SubjectFile]) -> list:
        if subject_files[0].label_images is None:
            if not all(s.label_images is None for s in subject_files):
                raise ValueError('inconsistent gt names in the subject list')
            return []
        gts = subject_files[0].label_images.keys()
        if not all(s.label_images.keys() == gts for s in subject_files):
            raise ValueError('inconsistent gt names in the subject list')
        return list(gts)
