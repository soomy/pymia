import abc
import pickle
import typing as t

import numpy as np
import SimpleITK as sitk

import miapy.data.conversion as conv
import miapy.data.definition as df
import miapy.data.indexexpression as expr
from . import reader as rd


class Extractor(metaclass=abc.ABCMeta):
    """Represents an extractor that extracts data from a dataset."""

    @abc.abstractmethod
    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        pass


class ComposeExtractor(Extractor):
    """Composes multiple Extractor objects."""

    def __init__(self, extractors) -> None:
        super().__init__()
        self.extractors = extractors

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        for e in self.extractors:
            e.extract(reader, params, extracted)


class NamesExtractor(Extractor):
    """Extracts the names of the entries within a category (i.e. the name of the enum identifying the data).

    The names are of type str.
    """

    def __init__(self, cache: bool=True, categories=('images', 'labels')) -> None:
        super().__init__()
        self.cache = cache
        self.cached_result = None
        self.categories = categories

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        if not self.cache or self.cached_result is None:
            d = self._extract(reader)
            self.cached_result = d
        else:
            d = self.cached_result

        for k, v in d.items():
            extracted[k] = v

    def _extract(self, reader: rd.Reader):
        d = {}
        for category in self.categories:
            d['{}_names'.format(category)] = reader.read(df.NAMES_PLACEHOLDER.format(category))
        return d


class SubjectExtractor(Extractor):
    """Extracts the subject's identification.

    The subject's identification is of type str.
    """

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        extracted['subject_index'] = params['subject_index']
        subject_index_expr = expr.IndexExpression(params['subject_index'])
        extracted['subject'] = reader.read(df.SUBJECT, subject_index_expr)


class IndexingExtractor(Extractor):
    """Extracts the index expression.

    The index expression is of type IndexExpression.
    """

    def __init__(self, do_pickle=False) -> None:
        super().__init__()
        self.do_pickle = do_pickle

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        extracted['subject_index'] = params['subject_index']
        index_expression = params['index_expr']
        if self.do_pickle:
            # pickle to prevent from problems since own class
            index_expression = pickle.dumps(index_expression)
        extracted['index_expr'] = index_expression


class ImagePropertiesExtractor(Extractor):
    """Extracts the image properties.

    The image properties are of type ImageProperties.
    """

    def __init__(self, do_pickle=False) -> None:
        super().__init__()
        self.do_pickle = do_pickle

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        subject_index_expr = expr.IndexExpression(params['subject_index'])

        shape = reader.read(df.INFO_SHAPE, subject_index_expr).tolist()
        direction = reader.read(df.INFO_DIRECTION, subject_index_expr).tolist()
        spacing = reader.read(df.INFO_SPACING, subject_index_expr).tolist()
        origin = reader.read(df.INFO_ORIGIN, subject_index_expr).tolist()

        # todo: everything in memory?
        image = sitk.Image(shape, sitk.sitkUInt8)
        image.SetDirection(direction)
        image.SetSpacing(spacing)
        image.SetOrigin(origin)
        # todo number_of_components_per_pixel and pixel_id

        img_properties = conv.ImageProperties(image)
        if self.do_pickle:
            # pickle to prevent from problems since own class
            img_properties = pickle.dumps(img_properties)
        extracted['properties'] = img_properties


class FilesExtractor(Extractor):
    """Extracts the file paths.

    The file paths are of type str.
    """

    def __init__(self, cache: bool=True, categories=('images', 'labels')) -> None:
        super().__init__()
        self.cache = cache
        self.cached_file_root = None
        self.categories = categories

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        subject_index_expr = expr.IndexExpression(params['subject_index'])

        if not self.cache or self.cached_file_root is None:
            file_root = reader.read(df.FILES_ROOT)
            self.cached_file_root = file_root
        else:
            file_root = self.cached_file_root

        extracted['file_root'] = file_root

        for category in self.categories:
            extracted['{}_files'.format(category)] = reader.read(df.FILES_PLACEHOLDER.format(category),
                                                                 subject_index_expr)


class SelectiveDataExtractor(Extractor):
    """Extracts data of a given category selectively."""

    def __init__(self, selection=None, category: str='labels') -> None:
        """Initializes a new instance of the SelectiveDataExtractor class.

        Args:
            selection (str or tuple): Entries within the category to select.
                If selection is None, the class has the same behaviour as the DataExtractor and selects all entries.
            category (str): The category to extract data from.
        """
        super().__init__()
        self.entry_base_names = None

        if isinstance(selection, str):
            selection = (selection,)
        self.selection = selection
        self.category = category

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        if '{}_names'.format(self.category) not in extracted:
            raise ValueError('selection of labels requires label_names to be extracted (use NamesExtractor)')

        if self.entry_base_names is None:
            entries = reader.get_subject_entries()
            self.entry_base_names = [entry.rsplit('/', maxsplit=1)[1] for entry in entries]

        if not reader.has(df.DATA_PLACEHOLDER.format(self.category)):
            raise ValueError('SelectiveDataExtractor requires {} to exist'.format(self.category))

        subject_index = params['subject_index']
        index_expr = params['index_expr']

        base_name = self.entry_base_names[subject_index]
        data = reader.read('{}/{}'.format(df.DATA_PLACEHOLDER.format(self.category), base_name), index_expr)
        label_names = extracted['{}_names'.format(self.category)]  # type: list

        if self.selection is None:
            extracted[self.category] = data
        else:
            selection_indices = np.array([label_names.index(s) for s in self.selection])
            extracted[self.category] = np.take(data, selection_indices, axis=-1)


class RandomDataExtractor(Extractor):
    """Extracts data of a given category randomly."""

    def __init__(self, selection=None, category: str='labels') -> None:
        """Initializes a new instance of the RandomDataExtractor class.

        Args:
            selection (str or tuple): Entries within the category to select an entry randomly from.
                If selection is None, an entry from all entries is randomly selected.
            selection (str or tuple): Note that if selection is None, all keys are considered.
            category (str): The category to extract data from.
        """
        super().__init__()
        self.entry_base_names = None

        if isinstance(selection, str):
            selection = (selection,)
        self.selection = selection
        self.category = category

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        if '{}_names'.format(self.category) not in extracted:
            raise ValueError('selection of labels requires label_names to be extracted (use NamesExtractor)')

        if self.entry_base_names is None:
            entries = reader.get_subject_entries()
            self.entry_base_names = [entry.rsplit('/', maxsplit=1)[1] for entry in entries]

        if not reader.has(df.DATA_PLACEHOLDER.format(self.category)):
            raise ValueError('SelectiveDataExtractor requires {} to exist'.format(self.category))

        subject_index = params['subject_index']
        index_expr = params['index_expr']

        base_name = self.entry_base_names[subject_index]
        data = reader.read('{}/{}'.format(df.DATA_PLACEHOLDER.format(self.category), base_name), index_expr)
        label_names = extracted['{}_names'.format(self.category)]  # type: list

        if self.selection is None:
            selection_indices = np.array(range(len(label_names)))
        else:
            selection_indices = np.array([label_names.index(s) for s in self.selection])

        random_index = np.random.choice(selection_indices)
        extracted[self.category] = np.take(data, random_index, axis=-1)


class ImageShapeExtractor(Extractor):

    def __init__(self, numpy_format=True) -> None:
        super().__init__()
        self.numpy_format = numpy_format

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        subject_index_expr = expr.IndexExpression(params['subject_index'])

        shape = reader.read(df.INFO_SHAPE, subject_index_expr)
        if self.numpy_format:
            tmp = shape[0]
            shape[0] = shape[-1]
            shape[-1] = tmp

        extracted['shape'] = tuple(shape.tolist())


class DataExtractor(Extractor):

    def __init__(self, categories=('images',), entire_subject: bool=False) -> None:
        super().__init__()
        self.categories = categories
        self.entire_subject = entire_subject
        self.entry_base_names = None

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        if self.entry_base_names is None:
            entries = reader.get_subject_entries()
            self.entry_base_names = [entry.rsplit('/', maxsplit=1)[1] for entry in entries]

        subject_index = params['subject_index']
        index_expr = params['index_expr']

        base_name = self.entry_base_names[subject_index]
        for category in self.categories:
            if self.entire_subject:
                data = reader.read('{}/{}'.format(df.DATA_PLACEHOLDER.format(category), base_name))
            else:
                data = reader.read('{}/{}'.format(df.DATA_PLACEHOLDER.format(category), base_name), index_expr)
            extracted[category] = data


class PadPatchDataExtractor(Extractor):

    def __init__(self, padding: t.Union[tuple, t.List[tuple]], categories=('images',)) -> None:
        super().__init__()
        self.categories = categories
        self.entry_base_names = None

        if isinstance(padding, tuple):
            padding = [(pad, pad) for pad in padding]
        index_diffs = np.asarray(padding)
        index_diffs[:, 0] = -index_diffs[:, 0]
        self.index_diffs = index_diffs

    def extract(self, reader: rd.Reader, params: dict, extracted: dict) -> None:
        if self.entry_base_names is None:
            entries = reader.get_subject_entries()
            self.entry_base_names = [entry.rsplit('/', maxsplit=1)[1] for entry in entries]

        subject_index = params['subject_index']
        index_expr = params['index_expr']  # type: expr.IndexExpression
        padded_indexing = np.asarray(index_expr.get_indexing()) + self.index_diffs

        padded_shape = tuple((padded_indexing[:, 1] - padded_indexing[:, 0]).tolist())

        sub_indexing = padded_indexing.copy()
        sub_indexing[padded_indexing > 0] = 0
        sub_indexing = -sub_indexing

        padded_indexing[padded_indexing < 0] = 0  # cannot slice outside the boundary
        padded_index_expr = expr.IndexExpression(padded_indexing.tolist())

        base_name = self.entry_base_names[subject_index]
        for category in self.categories:
            data = reader.read('{}/{}'.format(df.DATA_PLACEHOLDER.format(category), base_name), padded_index_expr)

            full_pad_shape = padded_shape + data.shape[len(padded_shape):]
            pad_data = np.zeros(full_pad_shape, dtype=data.dtype)
            sub_indexing[:, 1] = sub_indexing[:, 0] + data.shape[:sub_indexing.shape[0]]
            sub_index_expr = expr.IndexExpression(sub_indexing.tolist())

            pad_data[sub_index_expr.expression] = data
            extracted[category] = pad_data
