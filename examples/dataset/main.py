import argparse

import numpy as np

import pymia.data.conversion as pymia_conv
import pymia.data.extraction as pymia_extr
import pymia.data.assembler as pymia_asmbl
import pymia.evaluation.evaluator as pymia_eval
import pymia.evaluation.metric as pymia_metric

import examples.dataset.config as cfg


def batch_to_feed_dict(x_placeholder, y_placeholder, batch, is_train: bool=True) -> dict:
    feed_dict = {x_placeholder: np.stack(batch['images'], axis=0).astype(np.float32)}
    if is_train:
        feed_dict[y_placeholder] = np.stack(batch['labels'], axis=0).astype(np.int16)

    return feed_dict


def collate_batch(batch) -> dict:
    # batch is a list of dicts -> change to dict of lists
    return dict(zip(batch[0], zip(*[d.values() for d in batch])))


def init_evaluator() -> pymia_eval.Evaluator:
    evaluator = pymia_eval.Evaluator(pymia_eval.ConsoleEvaluatorWriter(5))
    evaluator.add_label(1, 'Structure 1')
    evaluator.add_label(2, 'Structure 2')
    evaluator.add_label(3, 'Structure 3')
    evaluator.add_label(4, 'Structure 4')
    evaluator.metrics = [pymia_metric.DiceCoefficient()]
    return evaluator


def main(config_file: str):
    config = cfg.load(config_file, cfg.Configuration)
    print(config)

    indexing_strategy = pymia_extr.SliceIndexing()  # slice-wise extraction
    extraction_transform = None  # we do not want to apply any transformation on the slices after extraction
    # define an extractor for training, i.e. what information we would like to extract per sample
    train_extractor = pymia_extr.ComposeExtractor([pymia_extr.NamesExtractor(),
                                                   pymia_extr.DataExtractor(),
                                                   pymia_extr.SelectiveDataExtractor()])

    # define an extractor for testing, i.e. what information we would like to extract per sample
    # not that usually we don't use labels for testing, i.e. the SelectiveDataExtractor is only used for this example
    test_extractor = pymia_extr.ComposeExtractor([pymia_extr.NamesExtractor(),
                                                  pymia_extr.IndexingExtractor(),
                                                  pymia_extr.DataExtractor(),
                                                  pymia_extr.SelectiveDataExtractor(),
                                                  pymia_extr.ImageShapeExtractor()])

    # define an extractor for evaluation, i.e. what information we would like to extract per sample
    eval_extractor = pymia_extr.ComposeExtractor([pymia_extr.NamesExtractor(),
                                                  pymia_extr.SubjectExtractor(),
                                                  pymia_extr.SelectiveDataExtractor(),
                                                  pymia_extr.ImagePropertiesExtractor()])

    # define the data set
    dataset = pymia_extr.ParameterizableDataset(config.database_file,
                                                indexing_strategy,
                                                pymia_extr.SubjectExtractor(),  # for select_indices() below
                                                extraction_transform)

    # generate train / test split for data set
    # we use Subject_0, Subject_1 and Subject_2 for training and Subject_3 for testing
    sampler_ids_train = pymia_extr.select_indices(dataset,
                                                  pymia_extr.SubjectSelection(('Subject_0', 'Subject_1', 'Subject_2')))
    sampler_ids_test = pymia_extr.select_indices(dataset,
                                                 pymia_extr.SubjectSelection(('Subject_3')))

    # set up training data loader
    training_sampler = pymia_extr.SubsetRandomSampler(sampler_ids_train)
    training_loader = pymia_extr.DataLoader(dataset, config.batch_size_training, sampler=training_sampler,
                                            collate_fn=collate_batch, num_workers=1)

    # set up testing data loader
    testing_sampler = pymia_extr.SubsetSequentialSampler(sampler_ids_test)
    testing_loader = pymia_extr.DataLoader(dataset, config.batch_size_testing, sampler=testing_sampler,
                                           collate_fn=collate_batch, num_workers=1)

    sample = dataset.direct_extract(train_extractor, 0)  # extract a subject

    evaluator = init_evaluator()  # initialize evaluator

    for epoch in range(config.epochs):  # epochs loop
        dataset.set_extractor(train_extractor)
        for batch in training_loader:  # batches for training
            # feed_dict = batch_to_feed_dict(x, y, batch, True)  # e.g. for TensorFlow
            # train model, e.g.:
            # sess.run([train_op, loss], feed_dict=feed_dict)
            pass

        # subject assembler for testing
        subject_assembler = pymia_asmbl.SubjectAssembler()

        dataset.set_extractor(test_extractor)
        for batch in testing_loader:  # batches for testing
            # feed_dict = batch_to_feed_dict(x, y, batch, False)  # e.g. for TensorFlow
            # test model, e.g.:
            # prediction = sess.run(y_model, feed_dict=feed_dict)
            prediction = np.stack(batch['labels'], axis=0)  # we use the labels as predictions such that we can validate the assembler
            subject_assembler.add_batch(prediction, batch)

        # evaluate all test images
        for subject_idx in list(subject_assembler.predictions.keys()):
            # convert prediction and labels back to SimpleITK images
            sample = dataset.direct_extract(eval_extractor, subject_idx)
            label_image = pymia_conv.NumpySimpleITKImageBridge.convert(sample['labels'],
                                                                       sample['properties'])

            assembled = subject_assembler.get_assembled_subject(sample['subject_index'])
            prediction_image = pymia_conv.NumpySimpleITKImageBridge.convert(assembled, sample['properties'])
            evaluator.evaluate(prediction_image, label_image, sample['subject'])  # evaluate prediction


if __name__ == '__main__':
    """The program's entry point.

    Parse the arguments and run the program.
    """

    parser = argparse.ArgumentParser(description='Main script using the dataset.')

    parser.add_argument(
        '--config_file',
        type=str,
        default='config.json',
        help='Path to the configuration file.'
    )

    args = parser.parse_args()
    main(args.config_file)
