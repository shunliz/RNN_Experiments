import logging

import os

import numpy as np

import theano

from blocks.algorithms import (Adam, CompositeRule, GradientDescent,
                               Momentum, RMSProp, StepClipping,
                               RemoveNotFinite)
from blocks.extensions import Printing, ProgressBar
from blocks.extensions.monitoring import (
    TrainingDataMonitoring, DataStreamMonitoring)
from blocks.extensions.saveload import Load
from blocks.graph import ComputationGraph
from blocks.main_loop import MainLoop
from blocks.model import Model
from extensions import EarlyStopping, TextGenerationExtension, ResetStates
# from blocks.extensions.saveload import Checkpoint


floatX = theano.config.floatX
logging.basicConfig(level='INFO')
logger = logging.getLogger(__name__)


def learning_algorithm(args):
    name = args.algorithm
    learning_rate = float(args.learning_rate)
    momentum = args.momentum
    clipping_threshold = args.clipping
    if name == 'adam':
        clipping = StepClipping(threshold=np.cast[floatX](clipping_threshold))
        adam = Adam(learning_rate=learning_rate)
        # [adam, clipping] means 'step clipping'
        # [clipping, adam] means 'gradient clipping'
        step_rule = CompositeRule([adam, clipping])
    elif name == 'rms_prop':
        clipping = StepClipping(threshold=np.cast[floatX](clipping_threshold))
        rms_prop = RMSProp(learning_rate=learning_rate)
        rm_non_finite = RemoveNotFinite()
        step_rule = CompositeRule([clipping, rms_prop, rm_non_finite])
    else:
        clipping = StepClipping(threshold=np.cast[floatX](clipping_threshold))
        sgd_momentum = Momentum(learning_rate=learning_rate, momentum=momentum)
        rm_non_finite = RemoveNotFinite()
        step_rule = CompositeRule([clipping, sgd_momentum, rm_non_finite])
    return step_rule


def train_model(cost, cross_entropy, updates,
                train_stream, valid_stream, args):

    # Define the model
    model = Model(cost)

    step_rule = learning_algorithm(args)
    cg = ComputationGraph(cost)
    logger.info(cg.parameters)

    algorithm = GradientDescent(cost=cost, step_rule=step_rule,
                                params=cg.parameters)
    algorithm.add_updates(updates)

    # extensions to be added
    extensions = []
    if args.load_path is not None:
        extensions.append(Load(args.load_path))

    outputs = [
        variable for variable in cg.variables if variable.name == "presoft"]

    extensions.append(TextGenerationExtension(
        outputs=outputs,
        generation_length=100,
        initial_text_length=args.initial_text_length,
        every_n_batches=args.monitoring_freq,
        plot_probability=True,
        softmax_sampling=args.softmax_sampling,
        dataset=args.dataset,
        updates=updates))
    extensions.extend([
        TrainingDataMonitoring([cost], prefix='train'),
        DataStreamMonitoring([cost, cross_entropy],
                             valid_stream, prefix='valid',
                             every_n_batches=args.monitoring_freq),
        ResetStates([v for v, _ in updates], every_n_batches=100),
        ProgressBar()])
    # Creating directory for saving model.
    if (not os.path.exists(args.save_path)) and (not args.interactive_mode):
        os.makedirs(args.save_path)
    else:
        raise Exception('Directory already exists')
    early_stopping = EarlyStopping('valid_cross_entropy',
                                   args.patience, args.save_path,
                                   every_n_batches=args.monitoring_freq)
    # extensions.append(Checkpoint(args.save_path,
    #                              every_n_batches=args.monitoring_freq,
    #                              save_separately=['log']))
    extensions.append(early_stopping)
    extensions.append(Printing(every_n_batches=args.monitoring_freq))

    main_loop = MainLoop(
        model=model,
        data_stream=train_stream,
        algorithm=algorithm,
        extensions=extensions
    )
    if args.interactive_mode:
        Load(args.load_path).load_to(main_loop)
        import ipdb
        ipdb.set_trace()
    else:
        main_loop.run()
