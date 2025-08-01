# Copyright 2017-2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import os
import re
import boto3
import pytest
from packaging.specifiers import SpecifierSet
from sagemaker.tensorflow import TensorFlow
from sagemaker.tuner import HyperparameterTuner, IntegerParameter
from six.moves.urllib.parse import urlparse
from packaging.version import Version

from ..... import invoke_sm_helper_function
from test.test_utils import is_pr_context, SKIP_PR_REASON
from test.test_utils import get_framework_and_version_from_tag, get_cuda_version_from_tag
from ...integration.utils import processor, py_version, unique_name_from_base  # noqa: F401
from .timeout import timeout


def can_run_mnist_estimator(ecr_image):
    _, image_framework_version = get_framework_and_version_from_tag(ecr_image)
    return Version(image_framework_version) in SpecifierSet("<2.6")


def validate_or_skip_test(ecr_image):
    if not can_run_mnist_estimator(ecr_image):
        pytest.skip("Mnist Estimator related scripts can only run for versions < 2.6")


RESOURCE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "resources")


@pytest.mark.skipif(is_pr_context(), reason=SKIP_PR_REASON)
@pytest.mark.model("mnist")
@pytest.mark.team("frameworks")
@pytest.mark.deploy_test
def test_mnist(ecr_image, sagemaker_regions, instance_type, framework_version):
    invoke_sm_helper_function(
        ecr_image, sagemaker_regions, _test_mnist_function, instance_type, framework_version
    )


def _test_mnist_function(ecr_image, sagemaker_session, instance_type, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        instance_type=instance_type,
        instance_count=1,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )

    estimator = _disable_sm_profiler(sagemaker_session.boto_region_name, estimator)

    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data"), key_prefix="scriptmode/mnist"
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-sagemaker-mnist"))
    _assert_s3_file_exists(sagemaker_session.boto_region_name, estimator.model_data)


@pytest.mark.model("mnist")
@pytest.mark.team("frameworks")
@pytest.mark.deploy_test
@pytest.mark.skip_gpu
def test_hc_mnist(ecr_image, sagemaker_regions, instance_type, framework_version):
    from sagemaker.instance_group import InstanceGroup

    instance_type = instance_type or "ml.c5.xlarge"
    training_group = InstanceGroup("train_group", instance_type, 1)
    invoke_sm_helper_function(
        ecr_image, sagemaker_regions, _test_mnist_hc_function, [training_group], framework_version
    )


def _test_mnist_hc_function(ecr_image, sagemaker_session, instance_groups, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        instance_groups=instance_groups,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )

    estimator = _disable_sm_profiler(sagemaker_session.boto_region_name, estimator)

    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data"), key_prefix="scriptmode/mnist"
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-hc-sagemaker-mnist"))
    _assert_s3_file_exists(sagemaker_session.boto_region_name, estimator.model_data)


@pytest.mark.skipif(is_pr_context(), reason=SKIP_PR_REASON)
@pytest.mark.model("mnist")
@pytest.mark.team("frameworks")
@pytest.mark.multinode(2)
@pytest.mark.integration("no parameter server")
def test_distributed_mnist_no_ps(ecr_image, sagemaker_regions, instance_type, framework_version):
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_distributed_mnist_no_ps_function,
        instance_type,
        framework_version,
    )


def _test_distributed_mnist_no_ps_function(
    ecr_image, sagemaker_session, instance_type, framework_version
):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        instance_count=2,
        instance_type=instance_type,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )
    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data"), key_prefix="scriptmode/mnist"
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-sm-distributed-mnist"))
    _assert_s3_file_exists(sagemaker_session.boto_region_name, estimator.model_data)


@pytest.mark.model("mnist")
@pytest.mark.multinode(2)
@pytest.mark.integration("parameter server")
@pytest.mark.team("frameworks")
def test_distributed_mnist_ps(ecr_image, sagemaker_regions, instance_type, framework_version):
    validate_or_skip_test(ecr_image=ecr_image)
    print("ecr image used for training", ecr_image)
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_distributed_mnist_ps_function,
        instance_type,
        framework_version,
    )


def _test_distributed_mnist_ps_function(
    ecr_image, sagemaker_session, instance_type, framework_version
):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_estimator.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        hyperparameters={"sagemaker_parameter_server_enabled": True},
        instance_count=2,
        instance_type=instance_type,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )
    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data-distributed"),
        key_prefix="scriptmode/mnist-distributed",
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-sm-distributed-mnist"))
    _assert_checkpoint_exists(sagemaker_session.boto_region_name, estimator.model_dir, 0)


@pytest.mark.model("mnist")
@pytest.mark.multinode(2)
@pytest.mark.integration("parameter server")
@pytest.mark.team("frameworks")
@pytest.mark.skip_cpu
def test_hc_distributed_mnist_ps(ecr_image, sagemaker_regions, instance_type, framework_version):
    from sagemaker.instance_group import InstanceGroup

    validate_or_skip_test(ecr_image=ecr_image)
    print("ecr image used for training", ecr_image)
    instance_type = instance_type or "ml.g5.4xlarge"
    training_group = InstanceGroup("train_group", instance_type, 2)
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_hc_distributed_mnist_ps_function,
        [training_group],
        framework_version,
    )


def _test_hc_distributed_mnist_ps_function(
    ecr_image, sagemaker_session, instance_groups, framework_version
):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_estimator.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        hyperparameters={"sagemaker_parameter_server_enabled": True},
        instance_groups=instance_groups,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )
    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data-distributed"),
        key_prefix="scriptmode/mnist-distributed",
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-hc-sm-distributed-mnist"))
    _assert_checkpoint_exists(sagemaker_session.boto_region_name, estimator.model_dir, 0)


## Skip test for TF2.16 image due to TF-IO s3 filesystem issue: https://github.com/tensorflow/io/issues/2039 impacting parameter server
@pytest.mark.model("mnist")
@pytest.mark.multinode(2)
@pytest.mark.integration("parameter server")
@pytest.mark.team("frameworks")
def test_distributed_mnist_custom_ps(
    ecr_image,
    sagemaker_regions,
    instance_type,
    framework_version,
    skip_tf216_only,
    skip_tf218_only,
    skip_tf219_only,
):
    print("ecr image used for training", ecr_image)
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_distributed_mnist_custom_ps,
        instance_type,
        framework_version,
    )


def _test_distributed_mnist_custom_ps(
    ecr_image, sagemaker_session, instance_type, framework_version
):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_custom.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        hyperparameters={"sagemaker_parameter_server_enabled": True},
        instance_count=2,
        instance_type=instance_type,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )
    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data-distributed"),
        key_prefix="scriptmode/mnist-distributed",
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-sm-distributed-mnist"))
    _assert_checkpoint_exists_v2(sagemaker_session.boto_region_name, estimator.model_dir, 10)


@pytest.mark.model("mnist")
@pytest.mark.integration("s3 plugin")
@pytest.mark.team("frameworks")
def test_s3_plugin(
    ecr_image,
    sagemaker_regions,
    instance_type,
    framework_version,
    skip_tf216_only,
    skip_tf218_only,
    skip_tf219_only,
):
    invoke_sm_helper_function(
        ecr_image, sagemaker_regions, _test_s3_plugin_function, instance_type, framework_version
    )


def _test_s3_plugin_function(ecr_image, sagemaker_session, instance_type, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_custom.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        hyperparameters={
            # Saving a checkpoint after every 5 steps to hammer the S3 plugin
            "save-checkpoint-steps": 10,
            # Reducing throttling for checkpoint and model saving
            "throttle-secs": 1,
            # Without the patch training jobs would fail around 100th to
            # 150th step
            "max-steps": 200,
            # Large batch size would result in a larger checkpoint file
            "batch-size": 1024,
            # This makes the training job exporting model during training.
            # Stale model garbage collection will also be performed.
            "export-model-during-training": True,
        },
        instance_count=1,
        instance_type=instance_type,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )

    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data-distributed"),
        key_prefix="scriptmode/mnist-distributed",
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-sm-s3-mnist"))
    print("=========== Model data location ===============")
    print(estimator.model_data)
    print("=========== Model dir           ===============")
    print(estimator.model_dir)
    _assert_checkpoint_exists_v2(sagemaker_session.boto_region_name, estimator.model_dir, 10)


## Skip test for TF2.16 image due to TF-IO s3 filesystem issue: https://github.com/tensorflow/io/issues/2039 impacting s3 plugin
@pytest.mark.model("mnist")
@pytest.mark.integration("s3 plugin")
@pytest.mark.team("frameworks")
@pytest.mark.skip_gpu
def test_hc_s3_plugin(
    ecr_image,
    sagemaker_regions,
    instance_type,
    framework_version,
    skip_tf216_only,
    skip_tf218_only,
    skip_tf219_only,
):
    from sagemaker.instance_group import InstanceGroup

    instance_type = instance_type or "ml.c5.xlarge"
    training_group = InstanceGroup("train_group", instance_type, 1)
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_hc_s3_plugin_function,
        [training_group],
        framework_version,
    )


def _test_hc_s3_plugin_function(ecr_image, sagemaker_session, instance_group, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_custom.py")
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        hyperparameters={
            # Saving a checkpoint after every 5 steps to hammer the S3 plugin
            "save-checkpoint-steps": 10,
            # Reducing throttling for checkpoint and model saving
            "throttle-secs": 1,
            # Without the patch training jobs would fail around 100th to
            # 150th step
            "max-steps": 200,
            # Large batch size would result in a larger checkpoint file
            "batch-size": 1024,
            # This makes the training job exporting model during training.
            # Stale model garbage collection will also be performed.
            "export-model-during-training": True,
        },
        instance_groups=instance_group,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )

    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data-distributed"),
        key_prefix="scriptmode/mnist-distributed",
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-tf-hc-sm-s3-mnist"))
    print("=========== Model data location ===============")
    print(estimator.model_data)
    print("=========== Model dir           ===============")
    print(estimator.model_dir)
    _assert_checkpoint_exists_v2(sagemaker_session.boto_region_name, estimator.model_dir, 10)


@pytest.mark.skipif(is_pr_context(), reason=SKIP_PR_REASON)
@pytest.mark.model("mnist")
@pytest.mark.integration("hpo")
@pytest.mark.team("frameworks")
def test_tuning(ecr_image, sagemaker_regions, instance_type, framework_version):
    invoke_sm_helper_function(
        ecr_image, sagemaker_regions, _test_tuning_function, instance_type, framework_version
    )


def _test_tuning_function(ecr_image, sagemaker_session, instance_type, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist.py")

    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        instance_type=instance_type,
        instance_count=1,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
    )

    hyperparameter_ranges = {"epochs": IntegerParameter(1, 2)}
    objective_metric_name = "accuracy"
    metric_definitions = [{"Name": objective_metric_name, "Regex": "accuracy: ([0-9\\.]+)"}]

    tuner = HyperparameterTuner(
        estimator,
        objective_metric_name,
        hyperparameter_ranges,
        metric_definitions,
        max_jobs=2,
        max_parallel_jobs=2,
    )

    with timeout(minutes=20):
        inputs = estimator.sagemaker_session.upload_data(
            path=os.path.join(resource_path, "mnist", "data"), key_prefix="scriptmode/mnist"
        )

        tuning_job_name = unique_name_from_base("test-tf-sm-tuning", max_length=32)
        tuner.fit(inputs, job_name=tuning_job_name)
        tuner.wait()


@pytest.mark.usefixtures("feature_smdebug_present")
@pytest.mark.model("mnist")
@pytest.mark.integration("smdebug")
@pytest.mark.team("smdebug")
@pytest.mark.skip_py2_containers
def test_smdebug(
    ecr_image, sagemaker_regions, instance_type, framework_version, sm_below_tf213_only
):
    invoke_sm_helper_function(
        ecr_image, sagemaker_regions, _test_smdebug_function, instance_type, framework_version
    )


def _test_smdebug_function(ecr_image, sagemaker_session, instance_type, framework_version):
    resource_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    script = os.path.join(resource_path, "mnist", "mnist_smdebug.py")
    hyperparameters = {"smdebug_path": "/tmp/ml/output/tensors"}
    estimator = TensorFlow(
        entry_point=script,
        role="SageMakerRole",
        instance_type=instance_type,
        instance_count=1,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
        hyperparameters=hyperparameters,
    )
    inputs = estimator.sagemaker_session.upload_data(
        path=os.path.join(resource_path, "mnist", "data"), key_prefix="scriptmode/mnist_smdebug"
    )
    estimator.fit(inputs, job_name=unique_name_from_base("test-sagemaker-mnist-smdebug"))
    _assert_s3_file_exists(sagemaker_session.boto_region_name, estimator.model_data)


@pytest.mark.usefixtures("feature_smddp_present")
@pytest.mark.usefixtures("feature_smmp_present")
@pytest.mark.integration("smdataparallel_smmodelparallel")
@pytest.mark.processor("gpu")
@pytest.mark.model("mnist")
@pytest.mark.team("frameworks")
@pytest.mark.skip_cpu
@pytest.mark.skip_py2_containers
def test_smdataparallel_smmodelparallel_mnist(
    ecr_image, sagemaker_regions, instance_type, tmpdir, framework_version
):
    """
    Tests SM Distributed DataParallel and ModelParallel single-node via script mode
    This test has been added for SM DataParallelism and ModelParallelism tests for re:invent.
    TODO: Consider reworking these tests after re:Invent releases are done
    """
    invoke_sm_helper_function(
        ecr_image,
        sagemaker_regions,
        _test_smdataparallel_smmodelparallel_mnist_function,
        instance_type,
        tmpdir,
        framework_version,
    )


def _test_smdataparallel_smmodelparallel_mnist_function(
    ecr_image, sagemaker_session, instance_type, tmpdir, framework_version
):
    instance_type = "ml.p4d.24xlarge"
    _, image_framework_version = get_framework_and_version_from_tag(ecr_image)
    image_cuda_version = get_cuda_version_from_tag(ecr_image)
    if Version(image_framework_version) < Version("2.3.1") or image_cuda_version != "cu110":
        pytest.skip(
            "SMD Model and Data Parallelism are only supported on CUDA 11, and on TensorFlow 2.3.1 or higher"
        )
    smmodelparallel_path = os.path.join(RESOURCE_PATH, "smmodelparallel")
    test_script = "smdataparallel_smmodelparallel_mnist_script_mode.sh"
    estimator = TensorFlow(
        entry_point=test_script,
        role="SageMakerRole",
        instance_count=1,
        instance_type=instance_type,
        source_dir=smmodelparallel_path,
        sagemaker_session=sagemaker_session,
        image_uri=ecr_image,
        framework_version=framework_version,
        py_version="py3",
    )

    estimator = _disable_sm_profiler(sagemaker_session.boto_region_name, estimator)

    estimator.fit()


def _assert_checkpoint_exists_v2(region, model_dir, checkpoint_number):
    """
    Checking for v2 style checkpoints i.e. checkpoint and .index files
    """
    _assert_s3_file_exists(region, os.path.join(model_dir, "checkpoint"))
    _assert_s3_file_exists(
        region, os.path.join(model_dir, "model.ckpt-{}.index".format(checkpoint_number))
    )


def _assert_checkpoint_exists(region, model_dir, checkpoint_number):
    """
    Checking for v1 style checkpoints i.e. graph.pbtxt, .index files and meta
    """
    _assert_s3_file_exists(region, os.path.join(model_dir, "graph.pbtxt"))
    _assert_s3_file_exists(
        region, os.path.join(model_dir, "model.ckpt-{}.index".format(checkpoint_number))
    )
    _assert_s3_file_exists(
        region, os.path.join(model_dir, "model.ckpt-{}.meta".format(checkpoint_number))
    )


def _assert_s3_file_exists(region, s3_url):
    parsed_url = urlparse(s3_url)
    s3 = boto3.resource("s3", region_name=region)
    s3.Object(parsed_url.netloc, parsed_url.path.lstrip("/")).load()


def _disable_sm_profiler(region, estimator):
    """Disable SMProfiler feature for China regions"""

    if region in ("cn-north-1", "cn-northwest-1"):
        estimator.disable_profiler = True
    return estimator
