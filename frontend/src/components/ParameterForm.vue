<script setup lang="ts">
import type { Settings } from "../types";
defineProps<{ params: Settings; feature: string }>();
</script>
<template>
  <div class="form-grid">
    <template v-if="feature === 'course_all'"
      ><label class="field"
        >视频播放方式<select v-model="params.video.mode">
          <option value="hybrid">自动选择播放方式</option>
          <option value="instant">优先立即完成</option>
          <option value="real_time">按实际时长播放</option>
        </select></label
      ><label class="field"
        >同时播放的视频数<input
          v-model.number="params.video.max_workers"
          type="number"
          min="0"
          max="200" /></label></template
    ><template v-if="['course_all', 'independent_homework'].includes(feature)"
      ><label class="field"
        >答题来源<select v-model="params.answer.mode">
          <option value="ai">题库 + AI</option>
          <option value="tiku">仅使用题库</option>
          <option value="manual">由我手动答题</option>
        </select></label
      ><label class="field"
        >没有可靠答案时<select v-model="params.answer.no_answer_action">
          <option value="skip">跳过，留待处理</option>
          <option value="random">随机选择</option>
        </select></label
      ><label class="check"
        ><input
          v-model="params.answer.auto_submit"
          type="checkbox"
        />自动提交答案</label
      ><label class="check"
        ><input
          v-model="params.answer.fallback_to_tiku"
          type="checkbox"
        />使用在线题库</label
      ><label class="field"
        >提交前等待（秒）<input
          v-model.number="params.answer.submit_delay"
          type="number"
          min="0"
          max="600" /></label
    ></template>
  </div>
</template>
