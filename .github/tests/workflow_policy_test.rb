# frozen_string_literal: true
require 'minitest/autorun'
require 'yaml'

class WorkflowPolicyTest < Minitest::Test
  ROOT = File.expand_path('..', __dir__)

  def workflow(name)
    path = File.join(ROOT, 'workflows', name)
    assert File.file?(path), "missing #{name}"
    YAML.safe_load(File.read(path), aliases: true)
  end

  def test_dispatch_automatically_prepares_review_and_pauses_only_publish_job
    flow = workflow('publish-release.yml')
    triggers = flow['on'] || flow[true]
    assert_equal ['repository_dispatch'], triggers.keys
    assert_equal ['platform-release-ready'], triggers.dig('repository_dispatch', 'types')
    assert_equal false, flow.dig('concurrency', 'cancel-in-progress')
    assert_equal 'read', flow.dig('permissions', 'contents')
    review = flow.fetch('jobs').fetch('review')
    publish = flow.fetch('jobs').fetch('publish')
    refute review.key?('environment')
    assert_equal 'read', review.dig('permissions', 'contents')
    assert_equal 'review', publish.fetch('needs')
    assert_equal 'public-release', publish.dig('environment', 'name')
    assert_equal 'write', publish.dig('permissions', 'contents')
    assert_equal 'read', publish.dig('permissions', 'actions')
    assert_includes publish.fetch('if'), "github.ref == 'refs/heads/main'"
    assert_includes publish.fetch('if'), "github.repository == 'CraftedSignal/releases'"
    assert_includes publish.fetch('steps').last.fetch('run'), 'publish_release.py --publish'
    refute_includes review.fetch('steps').last.fetch('run'), '--publish'
    assert_equal '${{ github.sha }}', publish.fetch('steps').first.dig('with', 'ref')
    assert_equal false, publish.fetch('steps').first.dig('with', 'persist-credentials')
  end

  def test_every_publish_command_is_in_the_approval_environment
    Dir[File.join(ROOT, 'workflows', '*.yml')].each do |path|
      workflow(File.basename(path)).fetch('jobs').each_value do |job|
        next unless job.fetch('steps', []).any? { |step| step.fetch('run', '').include?('--publish') }
        assert_equal 'public-release', job.dig('environment', 'name')
      end
    end
  end

  def test_contents_write_is_only_granted_after_human_approval
    Dir[File.join(ROOT, 'workflows', '*.yml')].each do |path|
      flow = workflow(File.basename(path))
      assert_equal 'read', flow.dig('permissions', 'contents')
      flow.fetch('jobs').each_value do |job|
        next unless job.dig('permissions', 'contents') == 'write'
        assert_equal 'public-release', job.dig('environment', 'name')
        assert_equal 'review', job.fetch('needs')
        refute job.key?('continue-on-error')
      end
    end
  end

  def test_pull_requests_validate_scripts_and_workflows_without_write_credentials
    flow = workflow('validate.yml')
    triggers = flow['on'] || flow[true]
    assert triggers.key?('pull_request')
    assert_equal({'contents' => 'read'}, flow.fetch('permissions'))
    checks = flow.fetch('jobs').fetch('validate').fetch('steps')
    assert checks.any? { |step| step.fetch('run', '').include?('unittest discover') }
    assert checks.any? { |step| step.fetch('run', '').include?('workflow_policy_test.rb') }
    assert checks.any? { |step| step.fetch('run', '').include?('actionlint') }
    refute_includes File.read(File.join(ROOT, 'workflows', 'publish-release.yml')), 'secrets.RELEASE_APP'
  end
end
