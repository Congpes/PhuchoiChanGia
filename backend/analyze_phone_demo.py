"""Offline per-view camera signals for phone-02; no cross-view fusion/FSR."""
import json
from pathlib import Path
import cv2
import mediapipe as mp
from algorithms import calculate_angle
from camera_fusion import frontal_metrics, hip_flexion_from_body_axis, sagittal_trunk_frame_angle, normalize_sagittal_trunk_lean
from measurement_smoothing import smooth_camera_segments


def run():
    root=Path(__file__).parent/'demo_videos'/'phone-02'
    signals={k:[] for k in ['leftKnee','rightKnee','leftHip','rightHip','trunkFront','trunkSide']}
    for view in ['frontal','sagittal']:
        cap=cv2.VideoCapture(str(root/f'{view}.mp4'));n=0
        with mp.solutions.pose.Pose(model_complexity=1,smooth_landmarks=False,min_detection_confidence=.5,min_tracking_confidence=.45) as detector:
            while True:
                ok,frame=cap.read()
                if not ok:break
                # Fixed person-region crop excludes excess floor; angles use pixels.
                frame=frame[180:720,400:900] if view=='frontal' else frame[150:690,:]
                h,w=frame.shape[:2]
                result=detector.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                keys=['trunkSide'] if view=='frontal' else ['leftKnee','rightKnee','leftHip','rightHip','trunkFront']
                values={k:None for k in keys}
                if result.pose_landmarks:
                    lm=result.pose_landmarks.landmark
                    pt=lambda i:(lm[i].x*w,lm[i].y*h)
                    valid=lambda ids:all(lm[i].visibility>=.5 and 0<=lm[i].x<=1 and 0<=lm[i].y<=1 for i in ids)
                    if view=='sagittal':
                        for side,hip,knee,ankle in [('left',23,25,27),('right',24,26,28)]:
                            if valid([hip,knee,ankle]):values[side+'Knee']=180-calculate_angle(pt(hip),pt(knee),pt(ankle))
                            if valid([11,12,23,24,knee]):values[side+'Hip']=hip_flexion_from_body_axis(pt(11),pt(12),pt(23),pt(24),pt(knee),pt(hip))
                        if valid([11,12,23,24]):
                            angle,_=sagittal_trunk_frame_angle(pt(11),pt(12),pt(23),pt(24))
                            angle,_,_=normalize_sagittal_trunk_lean(angle,left_heel=pt(29) if valid([29,31]) else None,left_toe=pt(31) if valid([29,31]) else None,right_heel=pt(30) if valid([30,32]) else None,right_toe=pt(32) if valid([30,32]) else None,nose=pt(0),mid_shoulder=((pt(11)[0]+pt(12)[0])/2,(pt(11)[1]+pt(12)[1])/2))
                            values['trunkFront']=angle
                    elif valid([11,12,23,24]):
                        names={'left_shoulder':11,'right_shoulder':12,'left_hip':23,'right_hip':24,'left_knee':25,'right_knee':26,'left_ankle':27,'right_ankle':28}
                        mapped={name:{'x':lm[i].x,'y':lm[i].y,'visibility':lm[i].visibility} for name,i in names.items()}
                        values['trunkSide']=frontal_metrics(mapped,(w,h))['trunkLateralLean']
                for key in keys:signals[key].append(values[key])
                n+=1
        cap.release();print(view,n,flush=True)
    manifest_path=root/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['analysisStatus']='per_view_filtered_preview'
    manifest['cameraPreview']={'fps':30,'filter':'median5_then_mean5','rawPreserved':True,'crossViewFusion':False,
        'signals':{key:{'raw':values,'filtered':smooth_camera_segments(values),'validSamples':sum(v is not None for v in values)} for key,values in signals.items()}}
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:sum(v is not None for v in a) for k,a in signals.items()},flush=True)

if __name__=='__main__':run()
