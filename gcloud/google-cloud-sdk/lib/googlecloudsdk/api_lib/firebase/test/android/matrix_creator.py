# -*- coding: utf-8 -*- #
# Copyright 2017 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Create Android test matrices in Firebase Test Lab."""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import os
import uuid

from apitools.base.py import exceptions as apitools_exceptions

from googlecloudsdk.api_lib.firebase.test import matrix_creator_common
from googlecloudsdk.api_lib.firebase.test import matrix_ops
from googlecloudsdk.api_lib.firebase.test import util
from googlecloudsdk.calliope import exceptions
from googlecloudsdk.core import log
import six


def CreateMatrix(args, context, history_id, gcs_results_root, release_track):
  """Creates a new matrix test in Firebase Test Lab from the user's params.

  Args:
    args: an argparse namespace. All the arguments that were provided to this
      gcloud command invocation (i.e. group and command arguments combined).
    context: {str:obj} dict containing the gcloud command context, which
      includes the Testing API client+messages libs generated by Apitools.
    history_id: {str} A history ID to publish Tool Results to.
    gcs_results_root: the root dir for a matrix within the GCS results bucket.
    release_track: the release track that the command is invoked from.

  Returns:
    A TestMatrix object created from the supplied matrix configuration values.
  """
  creator = MatrixCreator(args, context, history_id, gcs_results_root,
                          release_track)
  return creator.CreateTestMatrix(uuid.uuid4().hex)


class MatrixCreator(object):
  """Creates a single test matrix based on user-supplied test arguments."""

  def __init__(self, args, context, history_id, gcs_results_root,
               release_track):
    """Construct a MatrixCreator to be used to create a single test matrix.

    Args:
      args: an argparse namespace. All the arguments that were provided to this
        gcloud command invocation (i.e. group and command arguments combined).
      context: {str:obj} dict containing the gcloud command context, which
        includes the Testing API client+messages libs generated by Apitools.
      history_id: {str} A history ID to publish Tool Results to.
      gcs_results_root: the root dir for a matrix within the GCS results bucket.
      release_track: the release track that the command is invoked from.
    """
    self._project = util.GetProject()
    self._args = args
    self._history_id = history_id
    self._gcs_results_root = gcs_results_root
    self._client = context['testing_client']
    self._messages = context['testing_messages']
    self._release_track = release_track

  def _BuildAppReference(self, filename):
    """Builds either a FileReference or an AppBundle message for a file."""
    if filename.endswith('.aab'):
      return None, self._messages.AppBundle(
          bundleLocation=self._BuildFileReference(filename))
    else:
      return self._BuildFileReference(filename), None

  def _BuildFileReference(self, filename):
    """Build a FileReference pointing to the GCS copy of a file."""
    return self._messages.FileReference(
        gcsPath=os.path.join(self._gcs_results_root,
                             os.path.basename(filename)))

  def _GetOrchestratorOption(self):
    orchestrator_options = (self._messages.AndroidInstrumentationTest.
                            OrchestratorOptionValueValuesEnum)
    if self._args.use_orchestrator is None:
      return orchestrator_options.ORCHESTRATOR_OPTION_UNSPECIFIED
    elif self._args.use_orchestrator:
      return orchestrator_options.USE_ORCHESTRATOR
    else:
      return orchestrator_options.DO_NOT_USE_ORCHESTRATOR

  def _BuildRoboDirectives(self, robo_directives_dict):
    """Build a list of RoboDirectives from the dictionary input."""
    robo_directives = []
    action_types = self._messages.RoboDirective.ActionTypeValueValuesEnum
    action_type_mapping = {
        'click': action_types.SINGLE_CLICK,
        'text': action_types.ENTER_TEXT,
        'ignore': action_types.IGNORE
    }
    for key, value in six.iteritems((robo_directives_dict or {})):
      (action_type, resource_name) = util.ParseRoboDirectiveKey(key)
      robo_directives.append(
          self._messages.RoboDirective(
              resourceName=resource_name,
              inputText=value,
              actionType=action_type_mapping.get(action_type)))
    return robo_directives

  def _BuildAndroidInstrumentationTestSpec(self):
    """Build a TestSpecification for an AndroidInstrumentationTest."""
    spec = self._BuildGenericTestSpec()
    app_apk, app_bundle = self._BuildAppReference(self._args.app)
    spec.androidInstrumentationTest = self._messages.AndroidInstrumentationTest(
        appApk=app_apk,
        appBundle=app_bundle,
        testApk=self._BuildFileReference(self._args.test),
        appPackageId=self._args.app_package,
        testPackageId=self._args.test_package,
        testRunnerClass=self._args.test_runner_class,
        testTargets=(self._args.test_targets or []),
        orchestratorOption=self._GetOrchestratorOption())
    return spec

  def _BuildAndroidRoboTestSpec(self):
    """Build a TestSpecification for an AndroidRoboTest."""
    spec = self._BuildGenericTestSpec()
    app_apk, app_bundle = self._BuildAppReference(self._args.app)
    spec.androidRoboTest = self._messages.AndroidRoboTest(
        appApk=app_apk,
        appBundle=app_bundle,
        appPackageId=self._args.app_package,
        roboDirectives=self._BuildRoboDirectives(self._args.robo_directives))
    if getattr(self._args, 'robo_script', None):
      spec.androidRoboTest.roboScript = self._BuildFileReference(
          self._args.robo_script)
    return spec

  def _BuildAndroidGameLoopTestSpec(self):
    """Build a TestSpecification for an AndroidTestLoop."""
    spec = self._BuildGenericTestSpec()
    app_apk, app_bundle = self._BuildAppReference(self._args.app)
    spec.androidTestLoop = self._messages.AndroidTestLoop(
        appApk=app_apk,
        appBundle=app_bundle,
        appPackageId=self._args.app_package)
    if self._args.scenario_numbers:
      spec.androidTestLoop.scenarios = self._args.scenario_numbers
    if self._args.scenario_labels:
      spec.androidTestLoop.scenarioLabels = self._args.scenario_labels
    return spec

  def _BuildGenericTestSpec(self):
    """Build a generic TestSpecification without test-type specifics."""
    device_files = []
    for obb_file in self._args.obb_files or []:
      device_files.append(
          self._messages.DeviceFile(
              obbFile=self._messages.ObbFile(
                  obbFileName=os.path.basename(obb_file),
                  obb=self._BuildFileReference(obb_file))))
    for other_files in getattr(self._args, 'other_files', {}) or {}:
      device_files.append(
          self._messages.DeviceFile(
              regularFile=self._messages.RegularFile(
                  content=self._BuildFileReference(other_files),
                  devicePath=self._args.other_files[other_files])))

    environment_variables = []
    if self._args.environment_variables:
      for key, value in six.iteritems(self._args.environment_variables):
        environment_variables.append(
            self._messages.EnvironmentVariable(key=key, value=value))

    directories_to_pull = self._args.directories_to_pull or []

    account = None
    if self._args.auto_google_login:
      account = self._messages.Account(googleAuto=self._messages.GoogleAuto())

    additional_apks = [
        self._messages.Apk(location=self._BuildFileReference(additional_apk))
        for additional_apk in getattr(self._args, 'additional_apks', []) or []
    ]

    setup = self._messages.TestSetup(
        filesToPush=device_files,
        account=account,
        environmentVariables=environment_variables,
        directoriesToPull=directories_to_pull,
        networkProfile=getattr(self._args, 'network_profile', None),
        additionalApks=additional_apks)

    return self._messages.TestSpecification(
        testTimeout=matrix_ops.ReformatDuration(self._args.timeout),
        testSetup=setup,
        disableVideoRecording=not self._args.record_video,
        disablePerformanceMetrics=not self._args.performance_metrics)

  def _TestSpecFromType(self, test_type):
    """Map a test type into its corresponding TestSpecification message ."""
    if test_type == 'instrumentation':
      return self._BuildAndroidInstrumentationTestSpec()
    elif test_type == 'robo':
      return self._BuildAndroidRoboTestSpec()
    elif test_type == 'game-loop':
      return self._BuildAndroidGameLoopTestSpec()
    else:  # It's a bug in our arg validation if we ever get here.
      raise exceptions.InvalidArgumentException(
          'type', 'Unknown test type "{}".'.format(test_type))

  def _BuildTestMatrix(self, spec):
    """Build just the user-specified parts of a TestMatrix message.

    Args:
      spec: a TestSpecification message corresponding to the test type.

    Returns:
      A TestMatrix message.
    """
    if self._args.device:
      devices = [self._BuildAndroidDevice(d) for d in self._args.device]
      environment_matrix = self._messages.EnvironmentMatrix(
          androidDeviceList=self._messages.AndroidDeviceList(
              androidDevices=devices))
    else:
      environment_matrix = self._messages.EnvironmentMatrix(
          androidMatrix=self._messages.AndroidMatrix(
              androidModelIds=self._args.device_ids,
              androidVersionIds=self._args.os_version_ids,
              locales=self._args.locales,
              orientations=self._args.orientations))

    gcs = self._messages.GoogleCloudStorage(gcsPath=self._gcs_results_root)
    hist = self._messages.ToolResultsHistory(projectId=self._project,
                                             historyId=self._history_id)
    results = self._messages.ResultStorage(googleCloudStorage=gcs,
                                           toolResultsHistory=hist)

    client_info = matrix_creator_common.BuildClientInfo(
        self._messages,
        getattr(self._args, 'client_details', {}) or {}, self._release_track)

    return self._messages.TestMatrix(
        testSpecification=spec,
        environmentMatrix=environment_matrix,
        clientInfo=client_info,
        resultStorage=results,
        flakyTestAttempts=self._args.num_flaky_test_attempts or 0)

  def _BuildAndroidDevice(self, device_map):
    return self._messages.AndroidDevice(
        androidModelId=device_map['model'],
        androidVersionId=device_map['version'],
        locale=device_map['locale'],
        orientation=device_map['orientation'])

  def _BuildTestMatrixRequest(self, request_id):
    """Build a TestingProjectsTestMatricesCreateRequest for a test matrix.

    Args:
      request_id: {str} a unique ID for the CreateTestMatrixRequest.

    Returns:
      A TestingProjectsTestMatricesCreateRequest message.
    """
    spec = self._TestSpecFromType(self._args.type)
    return self._messages.TestingProjectsTestMatricesCreateRequest(
        projectId=self._project,
        testMatrix=self._BuildTestMatrix(spec),
        requestId=request_id)

  def CreateTestMatrix(self, request_id):
    """Invoke the Testing service to create a test matrix from the user's args.

    Args:
      request_id: {str} a unique ID for the CreateTestMatrixRequest.

    Returns:
      The TestMatrix response message from the TestMatrices.Create rpc.

    Raises:
      HttpException if the test service reports an HttpError.
    """
    request = self._BuildTestMatrixRequest(request_id)
    log.debug('TestMatrices.Create request:\n{0}\n'.format(request))
    try:
      response = self._client.projects_testMatrices.Create(request)
      log.debug('TestMatrices.Create response:\n{0}\n'.format(response))
    except apitools_exceptions.HttpError as error:
      msg = 'Http error while creating test matrix: ' + util.GetError(error)
      raise exceptions.HttpException(msg)

    log.status.Print('Test [{id}] has been created in the Google Cloud.'
                     .format(id=response.testMatrixId))
    return response
