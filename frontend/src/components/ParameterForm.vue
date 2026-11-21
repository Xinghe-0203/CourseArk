<script setup lang="ts">
import type { Settings } from "../types";
defineProps<{ params: Settings; feature: string }>();
</script>
<template>
  <div class="form-grid">
    <template v-if="feature === 'course_all'">
      <label class="field"
        >视频播放方式<select v-model="params.video.mode">
          <option value="hybrid">自动选择播放方式</option>
          <option value="instant">优先立即完成</option>
          <option value="real_time">按实际时长播放</option>
        </select>
        <small class="param-hint">自动选择会在不触发平台校验的前提下挑最省时的路径。</small></label
      >
      <label class="field"
        >同时播放的视频数<input
          v-model.number="params.video.max_workers"
          type="number"
          min="0"
          max="200" />
        <small class="param-hint">同时开几个视频。过大容易触发平台风控，建议不超过 8。</small></label
      >
    </template>
    <template v-if="['course_all', 'independent_homework', 'exam'].includes(feature)">
      <label class="field"
        >答题方式<select v-model="params.answer.mode">
          <option value="ai">AI 作答</option>
          <option value="manual">只抓题，由我手动作答</option>
        </select>
        <small class="param-hint">手动模式只读取题目，不提交任何答案。</small></label
      >
      <label class="field"
        >没有可靠答案时<select v-model="params.answer.no_answer_action">
          <option value="skip">跳过，留待处理</option>
          <option value="random">随机选择</option>
        </select>
        <small class="param-hint">缓存与 AI 都给不出可用答案时的处理方式。</small></label
      >
      <label class="check"
        ><input
          v-model="params.answer.auto_submit"
          type="checkbox"
        />自动提交答案<small class="param-hint inline">关闭后只作答不提交，由你在学习通里核对后再交。</small></label
      >
      <label class="field"
        >提交前等待（秒）<input
          v-model.number="params.answer.submit_delay"
          type="number"
          min="0"
          max="600" />
        <small class="param-hint">提交前停顿，避免整卷瞬间交上去。</small></label
      >
    </template>
  </div>
</template>
